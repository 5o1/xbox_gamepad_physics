"""CPU float64/float32 oracle checks, including discontinuous signal branches."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec('torch'),'Optional torch is not installed')
class TorchSignalsTest(unittest.TestCase):
    def setUp(self):
        import torch
        from xbox_gamepad_physics.motion import motion_from_dict
        from xbox_gamepad_physics.backends.common.signals_torch import TorchSignalMapper
        self.torch=torch;self.mapper_type=TorchSignalMapper
        self.motion=motion_from_dict(json.loads((ROOT/'build/resources/common/xbox_one_s/motion/full_controls.json').read_text()))

    def test_both_cpu_dtypes_match_oracle_and_preserve_pair(self):
        t=self.torch
        for dtype in (t.float64,t.float32):
            names=tuple(reversed(tuple(self.motion.joint_by_name)))
            mapper=self.mapper_type(self.motion,names,dtype=dtype)
            generator=t.Generator().manual_seed(20261016)
            q=t.rand((64,len(names)),generator=generator,dtype=dtype)*2-1
            for i,name in enumerate(names):
                j=self.motion.joint_by_name[name]
                q[:,i]*=max(abs(j.lower),abs(j.upper))*1.2
            q[0]=0
            for name,fraction in (('left_stick_x',.012),('left_stick_y',.016),('dpad_horizontal',.3)):
                q[1,names.index(name)]=fraction*self.motion.joint_by_name[name].upper
            for row,channel in enumerate(('left_stick_x','dpad_horizontal'),2):
                pivot=t.tensor((.02 if channel.startswith('left') else .3)*self.motion.joint_by_name[channel].upper,dtype=dtype)
                q[row]=0;q[row,names.index(channel)]=t.nextafter(pivot,t.tensor(float('inf'),dtype=dtype))
                q[row+2]=0;q[row+2,names.index(channel)]=t.nextafter(pivot,t.tensor(float('-inf'),dtype=dtype))
            batch=mapper.encode(q)
            decoded=mapper.decode_joint_targets(batch)
            self.assertEqual(len(decoded.names),19)
            self.assertNotIn('pair_press',decoded.names)
            for row in range(len(q)):
                positions={name:float(q[row,i]) for i,name in enumerate(names)}
                oracle=self.motion.signal_controller.encode(positions)
                expected=t.tensor(oracle.values,dtype=dtype)
                self.assertTrue(t.equal(batch.values[row]==0,expected==0),(dtype,row,batch.values[row],expected))
                t.testing.assert_close(batch.values[row],expected,rtol=1e-6 if dtype==t.float32 else 1e-14,atol=1e-7 if dtype==t.float32 else 1e-15)
                self.assertEqual(batch.available_mask[row].tolist(),list(oracle.available_mask))
                events=self.motion.signal_controller.encode_physical_events(positions)
                t.testing.assert_close(batch.events[row],t.tensor(list(events.values()),dtype=dtype))
                # Decode uses the batch's representable output values, not the
                # pre-cast oracle values, and does not impose action masks.
                from xbox_gamepad_physics.state import GamepadState
                state=GamepadState.from_mapping({name:float(batch.values[row,mapper.channels[name]]) for name in mapper.controller.available_channels},device_id=1,available_channels=mapper.controller.available_channels)
                expected_targets=mapper.controller.decode_joint_targets(state)
                t.testing.assert_close(decoded.values[row],t.tensor([expected_targets[n] for n in decoded.names],dtype=dtype))
            order=t.tensor([5,2,63,0])
            self.assertTrue(t.equal(mapper.encode(q[order]).values,batch.values[order]))
            self.assertEqual(tuple(mapper.encode(q[:0]).values.shape),(0,32))

    def test_all_discontinuities_and_partial_asymmetric_mapping(self):
        from xbox_gamepad_physics.controller import AxisSignalMapping, GamepadSignalController, RadialSignalGroup
        t=self.torch
        for dtype in (t.float32,t.float64):
            names=tuple(self.motion.joint_by_name)
            mapper=self.mapper_type(self.motion,names,dtype=dtype)
            vectors=[]
            boundaries=[(m.source,m.lower+m.neutral_epsilon*(m.upper-m.lower)) for m in mapper.controller.scalar_mappings]
            boundaries += [('left_stick_x',.02*self.motion.joint_by_name['left_stick_x'].upper),
                           ('dpad_horizontal',.3*self.motion.joint_by_name['dpad_horizontal'].upper),
                           ('dpad_horizontal',-.3*abs(self.motion.joint_by_name['dpad_horizontal'].lower))]
            for name,boundary in boundaries:
                pivot=t.tensor(boundary,dtype=dtype)
                for value in (pivot,t.nextafter(pivot,t.tensor(float('inf'),dtype=dtype)),t.nextafter(pivot,t.tensor(float('-inf'),dtype=dtype))):
                    row=t.zeros(20,dtype=dtype);row[names.index(name)]=value;vectors.append(row)
            q=t.stack(vectors);batch=mapper.encode(q)
            for index,row in enumerate(q):
                oracle=mapper.controller.encode(dict(zip(names,row.tolist())))
                self.assertEqual(batch.values[index].eq(0).tolist(),[value==0 for value in oracle.values])
            controller=GamepadSignalController.xbox_one_s(
                [AxisSignalMapping('left_x','left_stick_x',-.2,.4),AxisSignalMapping('left_y','left_stick_y',-.3,.5)],
                [RadialSignalGroup(('left_x','left_y'),1.,.02)])
            motion=replace(self.motion,signal_controller=controller)
            mapper=self.mapper_type(motion,('left_stick_y','left_stick_x'),dtype=dtype)
            q=t.tensor([[.1,-.1],[-.3,.4],[0,0]],dtype=dtype)
            result=mapper.encode(q)
            self.assertEqual(int(result.available_mask[0].sum()),2)
            self.assertEqual(result.events.shape[1],0)
            self.assertEqual(len(mapper.decode_joint_targets(result).names),2)
            for index,row in enumerate(q):
                oracle=controller.encode(dict(zip(mapper.joint_names,row.tolist())))
                t.testing.assert_close(result.values[index],t.tensor(oracle.values,dtype=dtype))

    def test_masks_and_invalid_inputs(self):
        t=self.torch;mapper=self.mapper_type(self.motion,tuple(self.motion.joint_by_name))
        q=t.zeros((2,20),dtype=t.float64)
        mask=mapper.available.clone();mask[0]=False
        batch=mapper.encode(q,task_mask=mask)
        self.assertFalse(bool(batch.task_mask[:,0].any()))
        self.assertTrue(t.equal(batch.action_mask,batch.available_mask&batch.task_mask))
        for value in (t.zeros((2,19),dtype=t.float64),t.full((2,20),float('nan'),dtype=t.float64)):
            with self.assertRaises(ValueError):mapper.encode(value)
        with self.assertRaises(ValueError):mapper.encode(q,task_mask=t.ones(32,dtype=t.bool))
        with self.assertRaises(ValueError):mapper.decode_event_targets(t.ones((2,1),dtype=t.float64)*2)


if __name__=='__main__':unittest.main()
