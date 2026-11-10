"""Force-awake station diagnostic; one backend call is one 1 ms physics step."""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def policy():
    from dexhand_workstation import collection
    original_factory=collection.create_backend
    records=[]
    def factory(*args,**kwargs):
        backend=original_factory(*args,**kwargs)
        original_step=backend.step
        root=backend.gamepad.articulation.root
        record=dict(method='root.wake_up before every 1 ms backend step',calls=0,
            sleeping_after_wake=0,sleeping_after_step=0,dt_s_values=[])
        records.append(record)
        def step(dt):
            root.wake_up()
            record['sleeping_after_wake']+=int(root.sleeping)
            result=original_step(dt)
            record['calls']+=1
            record['sleeping_after_step']+=int(root.sleeping)
            if dt not in record['dt_s_values']:record['dt_s_values'].append(dt)
            return result
        backend.step=step
        return backend
    with patch.object(collection,'create_backend',side_effect=factory):
        yield records
