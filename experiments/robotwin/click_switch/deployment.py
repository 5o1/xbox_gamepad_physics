"""1 ms time resampling of existing acceptance functions, process-only.

Keep the original source files, thresholds, force expressions and trajectory
state machine. Only clocks and sample counts change; archive transformed source.
"""
from contextlib import contextmanager, ExitStack
import copy
from dataclasses import replace
import hashlib
import inspect
import textwrap
from unittest.mock import patch


def adapted(module, name, substitutions, receipt):
    original=getattr(module,name)
    source=textwrap.dedent(inspect.getsource(original))
    converted=source
    edits=[]
    for before,after in substitutions:
        count=converted.count(before)
        if count==0:raise ValueError(f'resampling input missing {module.__name__}.{name}: {before!r}')
        converted=converted.replace(before,after)
        edits.append(dict(before=before,after=after,occurrences=count))
    namespace=dict(original.__globals__)
    exec(compile(converted,original.__code__.co_filename+':deployment-1ms','exec'),namespace)
    receipt['functions'].append(dict(module=module.__name__,name=name,edits=edits,
        original_sha256=hashlib.sha256(source.encode()).hexdigest(),
        adapted_sha256=hashlib.sha256(converted.encode()).hexdigest(),adapted_source=converted))
    return namespace[name]


@contextmanager
def policy():
    import tests.acceptance as acceptance
    from tests.acceptance import runner, scoring
    from tests.acceptance.robotwin import (executor,stick_click,stick_cone_production as cone,
        stick_click_t3_point_v2 as t3)
    receipt=dict(dt_s=.001,source_dt_s=.004,label='deployment diagnostic; not frozen 4 ms acceptance',functions=[])
    original_load=acceptance.load_suite
    def load_suite(*args,**kwargs):
        suite=original_load(*args,**kwargs)
        return replace(suite,fixture={**suite.fixture,'dt_s':.001},
            criteria={**suite.criteria,'hold_steps':500})
    click_protocol=copy.deepcopy(stick_click.P);click_protocol['dt_s']=.001
    receipt['effective_stick_click_protocol']=click_protocol
    receipt['effective_fixture']=dict(load_suite().fixture)
    receipt['effective_criteria']=dict(load_suite().criteria)
    with ExitStack() as stack:
        for module in (acceptance,executor,stick_click,t3):
            stack.enter_context(patch.object(module,'load_suite',side_effect=load_suite))
        stack.enter_context(patch.object(stick_click,'P',click_protocol))
        init=adapted(runner.PressTrajectory,'__init__',[('self.dt=.004','self.dt=.001')],receipt)
        stack.enter_context(patch.object(runner.PressTrajectory,'__init__',init))
        score=adapted(scoring,'score_case',[('125','500'),('*.004','*.001')],receipt)
        stack.enter_context(patch.object(scoring,'score_case',score))
        run_case=adapted(runner,'run_case',[('maximum_steps=10000','maximum_steps=40000'),('.004','.001')],receipt)
        stack.enter_context(patch.object(executor,'run_case',run_case))
        cone_run=adapted(cone,'run',[("p=json.loads(P.read_text());","p=json.loads(P.read_text());p['dt_s']=.001;"),
            ('range(500)','range(2000)'),('i<250','i<1000'),('*.004','*.001')],receipt)
        stack.enter_context(patch.object(cone,'run',cone_run))
        t3_run=adapted(t3,'run',[("p=json.loads(P.read_text());","p=json.loads(P.read_text());p['dt_s']=.001;"),
            (',250)',',1000)'),(',125)',',500)'),('hold[-125:]','hold[-500:]')],receipt)
        stack.enter_context(patch.object(t3,'run',t3_run))
        yield receipt
