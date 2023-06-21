import json
from datetime import datetime

from sqlalchemy.orm import Session
import string, random
import models, schemas

def get_user(db: Session, id: string):
    query = db.query(models.User).filter(models.User.id == id).first()
    return query


def create_user(db: Session, name: str):
    token = create_random_token()
    db_user = models.User(id=token, name=name, run_tokens=[])
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_all_users(db: Session):
    return db.query(models.User).all()


def get_all_token(db: Session):
    return db.query(models.RunToken).all()


def get_full_trace(db: Session):
    return db.query(models.RunTrace).all()


def get_run_trace(db: Session, token: models.RunToken):
    return db.query(models.RunTrace).filter(models.RunTrace.token == token.id).all()


def get_run_state(db: Session, token: models.RunToken):
    return get_run_state_information(get_run_trace(db, token))


def get_run_state_information(objects):
    ids = {}
    objects = sorted(objects, key=lambda obj: obj.timestamp)

    for entry in objects:
        splitted = entry.process.split(":")
        ids_entry = {
            "process": splitted[0],
            "sub_process": splitted[1] if len(splitted) > 1 else None,
            "status": entry.status
        }
        ids[entry.task_id] = ids_entry
    return ids


def get_run_state_information_combined(ids_json: dict):
    processes = {}
    for t_id, t_obj in ids_json.items():
        if t_obj["process"] in processes:
            process = processes[t_obj["process"]]
            subprocesses = process["sub_processes"]
            subprocesses_temp = [elem["name"] for elem in process["sub_processes"]]
            if t_obj["sub_process"] in subprocesses_temp:
                print(t_obj["sub_process"])
            subprocesses.append(
                {
                    "name": t_obj["sub_process"],
                    "task_id": t_id,
                    "status": t_obj["status"],
                    "status_score": get_status_score(t_obj["status"]),
                },
            )
        else:
            subprocesses = [
                {
                    "name": t_obj["sub_process"],
                    "task_id": t_id,
                    "status": t_obj["status"],
                    "status_score": get_status_score(t_obj["status"]),
                },
            ]
            processes[t_obj["process"]] = {"sub_processes": subprocesses}

    return processes


def get_status_score(status):
    if status == "RUNNING":
        return 1
    elif status == "COMPLETED":
        return 2
    else:
        return 0

def get_full_meta(db: Session):
    return db.query(models.RunMetadata).all()


def create_token(db: Session):
    token = create_random_token()
    db_token = models.RunToken(id=token)
    db.add(db_token)
    db.commit()
    db.refresh(db_token)
    return db_token


def get_token(db: Session, token_id: str):
    return db.query(models.RunToken).get(token_id)


def remove_token(db: Session, token):
    user = db.query(models.User).filter(models.User.run_tokens.contains([token.id])).first()
    if user:
        remove_token_from_user(db, user, token)
    db.delete(token)
    db.commit()
    return {"removed_token": token.id, "removed_from_user": user is not None}


def remove_all_token_from_user(user_id: str, db: Session):
    user = get_user(db, user_id)
    tokens = user.run_tokens
    user.run_tokens = []
    db.commit()
    db.refresh(user)
    return {"user": user_id, "removed_tokens": tokens}


def add_token_to_user(db: Session, user_id, token):
    user = get_user(db, user_id)
    if token.id not in user.run_tokens:
        user.run_tokens.append(token.id)
        db.commit()
        db.refresh(user)
        return {"added_token": token.id}
    return {"added_token": None}


def remove_token_from_user(db: Session, user, token):
    tokens = user.run_tokens
    try:
        idx = tokens.index(token.id)
    except ValueError:
        print(f"{token.id}: no such token in list of tokens for user {user.id}")
        return {"removed_token": None}
    new_tokens = [token for token in tokens if not tokens.index(token) == idx]
    user.run_tokens = new_tokens
    db.commit()
    db.refresh(user)

    return {"removed_token", token.id}

def persist_trace(db: Session, json_ob, token):
    """
    token = create_random_token()
            db_user = models.User(id=token, name=name)
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
        """
    metadata_saved = False
    trace_saved = False

    metadata = json_ob.get("metadata")
    if metadata is not None:
        run_name = json_ob.get("run_name")
        params = metadata.get("parameters")
        reference = None
        if params is not None:
            reference = params.get("reference")
        meta_object = models.RunMetadata(
            token=token.id,
            run_name=run_name,
            reference=reference
        )
        db.add(meta_object)
        db.commit()
        db.refresh(meta_object)
        metadata_saved = True
    trace = json_ob.get("trace")
    if trace is not None:
        task_id = trace.get("task_id")
        status = trace.get("status")
        run_name = json_ob.get("run_name")
        process = trace.get("process")
        name = trace.get("name")
        tag = trace.get("tag")
        cpus = trace.get("cpus")
        memory = trace.get("memory")
        disk = trace.get("disk")
        duration = trace.get("duration")
        trace_object = models.RunTrace(
            token=token.id,
            task_id=task_id,
            status=status,
            run_name=run_name,
            process=process,
            tag=tag,
            cpus=cpus,
            name=name,
            memory=memory,
            disk=disk,
            duration=duration,
            timestamp=datetime.utcnow(),
        )
        db.add(trace_object)
        db.commit()
        db.refresh(trace_object)
        trace_saved = True
    return {"metadata_saved": metadata_saved, "trace_saved": trace_saved}








def create_random_token():
    alphabet = string.ascii_lowercase + string.ascii_uppercase
    return ''.join((random.choice(alphabet) for i in range(0, 15)))

