import json
from datetime import datetime

from sqlalchemy.orm import Session
import string, random
import models, schemas, crud

def group_by_run_name(result_by_task):
    run_name_dictionary = {}
    for process in result_by_task:
        if process.run_name not in run_name_dictionary:
            run_name_dictionary[process.run_name] = [process]
        else:
            run_name_dictionary[process.run_name].append(process)

    return run_name_dictionary

"""
Analysis part
"""
INTERVAL_VALID_RAM_RELATION = (0.6, 1.2) # from 60 to 120%
INTERVAL_VALID_CPU_ALLOCATION_PERCENTAGE = (60, 140) # from 60 to 140%
THRESHOLD_DURATION_RELATION = 5 # a process can run 5 times longer than the average over the others
DURATION_TO_CONSIDER_AVERAGES_THRESHOLD = 120000 # two minutes threshold to consider only bigger processes
DURATION_REQUESTED_RELATION_THRESHOLD = 1.3 # process can run 30% longer than requested
TAG_DURATION_RATIO_THRESHOLD = 1.4 # processes with this tag are allowed
TAG_DURATION_RATIO_FULL_THRESHOLD = 0.3 # processes with a certain tag are allowed to take up to 30% of full duration
TAG_CPU_ALLOCATION_RATIO_THRESHOLD = 1.5 # 150% in relation to other processes
TAG_CPU_PERCENTAGE_RATIO_THRESHOLD = 1.5 # same
TAG_MEMORY_RSS_AVERAGE_RATIO_THRESHOLD = 1.4 # 140% memory in relation to others



def check_valid_ram_interval(process: models.RunTrace):
    if process.memory is not None and process.rss is not None:
        relative = process.rss / process.memory
        return INTERVAL_VALID_RAM_RELATION[0] <= relative <= INTERVAL_VALID_RAM_RELATION[1], {"ram_relative": relative}
    return True, None

def check_valid_cpu_interval(process: models.RunTrace):
    if process.cpus:
        if process.cpu_percentage:
            allocation = process.cpu_percentage / process.cpus
            return INTERVAL_VALID_CPU_ALLOCATION_PERCENTAGE[0] <= allocation <= INTERVAL_VALID_CPU_ALLOCATION_PERCENTAGE[1], {"cpu_allocation": allocation}
    return True, None


def analyze(grouped_processes):
    analysis = {}
    process_analysis = []
    tags_presave = []
    tag_process_mapping = []
    tag_analysis = []
    
    for key in grouped_processes:
        full_duration = []
        group = grouped_processes[key]
        execution_duration = []
        for process in group:
            if process.duration is not None: 
                full_duration.append(process.duration)
            tags = tags_from_process(process)
            for tag in tags:
                if tag not in tags_presave:
                    tags_presave.append(tag)
                    tag_process_mapping.append({"tag": tag})
                map_element = next((tag_map for tag_map in tag_process_mapping if tag_map["tag"] == tag))
                if not "processes" in map_element:
                    map_element["processes"] = []
                map_element["processes"].append(process)
            execution_duration.append({"process": process.process, "task_id": process.task_id, "duration": process.duration, "tags": tags})
        
        for process in group:
            process: models.RunTrace = process
            possible_return = { "process": process.process, "task_id": process.task_id, "run_name": process.run_name, "problems": [] }
            valid, problems = get_process_invalidities(process, execution_duration)
            if not valid:
                possible_return["problems"] = problems
                process_analysis.append(possible_return)
        full_duration = sum(full_duration) # there is a bug somewhere
        for tag in tag_process_mapping:
            valid, problems = get_tag_invalidities(tag, execution_duration, full_duration)
            if not valid:
                tag_analysis.append({"tag": tag["tag"], "run_name": key, "problems": problems})
    analysis["process_wise"] = process_analysis
    analysis["tag_wise"] = tag_analysis

    return analysis

def get_tag_invalidities(tag_obj, execution_duration_mapping, full_duration):
    valid = True
    problems = []
    same_tag_durations = []
    same_tag_memory = []
    same_tag_cpu_percentage = []
    same_tag_cpu_allocation = []
    without_tag_memory = []
    without_tag_cpu_percentage = []
    without_tag_cpu_allocation = []
    without_tag_durations = []
    for elem in execution_duration_mapping:
        if tag_obj["tag"] in elem["tags"]:
            for process in tag_obj["processes"]:
                if process.duration:
                    same_tag_durations.append(process.duration)
                if process.cpu_percentage:
                    same_tag_cpu_percentage.append(process.cpu_percentage)
                    if process.cpus:
                        same_tag_cpu_allocation.append(process.cpu_percentage / process.cpus)
                if process.rss:
                    same_tag_memory.append(process.rss)
        else:
            for process in tag_obj["processes"]:
                if process.duration:
                    without_tag_durations.append(process.duration)
                if process.cpu_percentage:
                    without_tag_cpu_percentage.append(process.cpu_percentage)
                    if process.cpus:
                        without_tag_cpu_allocation.append(process.cpu_percentage / process.cpus)
                if process.rss:
                    without_tag_memory.append(process.rss)

    # duration

    same_tag_duration_sum = sum(same_tag_durations)
    without_tag_duration_sum = sum(without_tag_durations)
    if len(same_tag_durations) > 0 and len(without_tag_durations) > 0:
        same_tag_duration_average = same_tag_duration_sum / len(same_tag_durations)
        without_tag_duration_average = without_tag_duration_sum / len(without_tag_durations)
        ratio_with_without = same_tag_duration_average / without_tag_duration_average
        if ratio_with_without > TAG_DURATION_RATIO_THRESHOLD:
            valid = False
            problems.append({"duration_comparison_ratio": ratio_with_without})
        ratio_with_full = same_tag_duration_sum / full_duration
        if ratio_with_full > TAG_DURATION_RATIO_FULL_THRESHOLD:
            valid = False
            problems.append({"duration_to_full_ratio": ratio_with_full})
    
    # cpu

    if len(same_tag_cpu_allocation) > 0 and len(without_tag_cpu_allocation) > 0:
        same_tag_cpu_allocation_average = sum(same_tag_cpu_allocation) / len(same_tag_cpu_allocation)
        without_tag_cpu_allocation_average = sum(without_tag_cpu_allocation) / len(without_tag_cpu_allocation)
        ratio = same_tag_cpu_allocation_average / without_tag_cpu_allocation_average
        if ratio > TAG_CPU_ALLOCATION_RATIO_THRESHOLD:
            valid = False
            problems.append({"cpu_allocation_ratio": ratio})

    if len(same_tag_cpu_percentage) > 0 and len(without_tag_cpu_percentage) > 0:
        same_tag_cpu_percentage_average =  sum(same_tag_cpu_percentage) / len(same_tag_cpu_percentage)
        without_tag_cpu_percentage_average =  sum(without_tag_cpu_percentage) / len(without_tag_cpu_percentage)
        ratio = same_tag_cpu_percentage_average / without_tag_cpu_percentage_average
        if ratio > TAG_CPU_PERCENTAGE_RATIO_THRESHOLD:
            valid = False
            problems.append({"cpu_percentage_ratio": ratio})
    
    # memory 

    if len(same_tag_memory) > 0 and len(without_tag_memory) > 0:
        same_tag_memory_average = sum(same_tag_memory) / len(same_tag_memory)
        without_tag_memory_average = sum(without_tag_memory) / len(without_tag_memory)
        ratio = same_tag_memory_average / without_tag_memory_average
        if ratio > TAG_MEMORY_RSS_AVERAGE_RATIO_THRESHOLD:
            valid = False
            problems.append({"memory_ratio": ratio})

    return valid, problems

def tags_from_process(process: models.RunTrace):
    tags = process.tag
    if tags is None or tags == '':
        return [{'_': None}]
    pairs = []
    splitted = tags.split(',')
    for splitted_string in splitted:
        splitted_string = splitted_string
        pair = splitted_string.split(':')
        if len(pair) > 1:
            pairs.append({pair[0].strip(), pair[1].strip()})
        else:
            pairs.append({'_': pair[0].strip()})
    return pairs




def get_process_invalidities(process: models.RunTrace, duration_mapping):
    invalidities_list = []
    to_return = False
    ram_valid, problems = check_valid_ram_interval(process)
    if not ram_valid:
        invalidities_list.append(problems)
        to_return = True

    cpu_valid, problems = check_valid_cpu_interval(process)
    if not cpu_valid:
        invalidities_list.append(problems)
        to_return = True
    
    duration_values_without_process = [dur_obj["duration"] for dur_obj in duration_mapping if dur_obj["process"] != process.process]
    duration_values_without_this_explicit_task = [dur_obj["duration"] for dur_obj in duration_mapping if dur_obj["process"] != process.process and dur_obj["task_id"] != process.task_id]
    duration_values_within_process = [dur_obj["duration"] for dur_obj in duration_mapping if dur_obj["process"] == process.process and dur_obj["task_id"] != process.task_id]
    
    if process.duration:
        if process.duration > DURATION_TO_CONSIDER_AVERAGES_THRESHOLD:
            len_duration_wo_p = len(duration_values_without_process)
            if len_duration_wo_p > 0:
                average_without_process = sum(duration_values_within_process) / len_duration_wo_p
                if average_without_process > THRESHOLD_DURATION_RELATION:
                    invalidities_list.append({"duration_ratio_compared_to_other_processes": average_without_process})
                    to_return = True

            len_duration_wo_et = len(duration_values_without_this_explicit_task)
            if len_duration_wo_et > 0:
                average_without_task = sum(duration_values_without_this_explicit_task) / len_duration_wo_et 
                if average_without_task > THRESHOLD_DURATION_RELATION:
                    invalidities_list.append({"duration_ratio_compared_to_all": average_without_task})
                    to_return = True

            len_duration_within = len(duration_values_within_process)
            if len_duration_within:
                average_within = sum(duration_values_within_process) / len_duration_within
                if average_within > THRESHOLD_DURATION_RELATION:
                    invalidities_list.append({"duration_ratio_compared_to_same": average_within})
                    to_return = True
        if process.time:
            duration_ratio = process.duration / process.time
            if duration_ratio > DURATION_REQUESTED_RELATION_THRESHOLD:
                invalidities_list.append({"duration_ratio_to_requested", duration_ratio})
                to_return = True
    return (not to_return, invalidities_list)
    
"""
End of analysis part
"""