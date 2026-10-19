"""Native spatial-tendon limits and read-only shaft-angle inspection.

MuJoCo solves limit reactions together with contacts. There is no post-step
state correction. Native compliance does not guarantee an exact hard boundary.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from xbox_gamepad_physics.backends.common.constraints import ShaftTiltLimit
from xbox_gamepad_physics.errors import AssetImportError, StateValidationError
from ._backend import require_mujoco
from .numerics import limit_policy


# Unit-direction coordinates, not a physical tendon or controller dimension.
DIRECTION_SCALE_M = 1.0


def _vector(values):
    return ' '.join(format(float(value), '.17g') for value in values)


def append_native_tilt_limits(xml, descriptions, *, policy=None):
    """Encode the common cone on the existing two-hinge motion chain.

    Both sites are measured from the common pivot. Separation is 2*L*sin(theta/2),
    so one native upper length limit defines the circular cone. Sites are upstream
    of the click slide and add neither mass nor degrees of freedom.
    """
    if not descriptions:
        return []
    policy = limit_policy() if policy is None else policy
    tendons = ET.SubElement(xml, 'tendon')
    mappings = []
    for record in descriptions:
        definition = ShaftTiltLimit.from_record(record)
        sites = []
        for side, link, axis in (
            ('reference', definition.reference_link, definition.reference_axis),
            ('moving', definition.moving_link, definition.moving_axis),
        ):
            body = next((item for item in xml.iter('body') if item.get('name') == link), None)
            if body is None:
                raise AssetImportError(f'{definition.name}: missing limit frame {link}')
            try:
                pivot = record[f'pivot_in_{side}_m']
            except KeyError as exc:
                raise AssetImportError(f'{definition.name}: native cone needs the common {side} pivot') from exc
            name = f'{definition.name}_{side}'
            position = [pivot[i] + DIRECTION_SCALE_M * axis[i] for i in range(3)]
            ET.SubElement(body, 'site', name=name, pos=_vector(position),
                          size='0.001', group='5', rgba='0 0 0 0')
            sites.append(name)
        maximum_length = 2 * DIRECTION_SCALE_M * math.sin(definition.maximum_rad / 2)
        name = definition.name + '_native'
        tendon = ET.SubElement(tendons, 'spatial', name=name, limited='true',
            range=_vector((0, maximum_length)), stiffness='0', damping='0',
            frictionloss='0', armature='0', margin='0',
            solreflimit=_vector(policy['solreflimit']), solimplimit=_vector(policy['solimplimit']),
            group='5', rgba='0 0 0 0')
        for site in sites:
            ET.SubElement(tendon, 'site', site=site)
        mappings.append({
            'id': definition.name, 'tendon': name, 'sites': sites,
            'direction_scale_m': DIRECTION_SCALE_M, 'range_m': [0., maximum_length],
            'equation': 'length = 2*direction_scale_m*sin(shaft_angle_rad/2)',
            'response': 'native_compliant_limit', 'strict_hard_limit_satisfied': False,
            'solreflimit': list(policy['solreflimit']), 'solimplimit': list(policy['solimplimit']),
            'policy_id': policy['policy_id'],
            'parameter_basis': 'Owner-selected numerical limit response, not measured hardware. See backend_options.mujoco.limit_response.',
            'source': 'https://github.com/google-deepmind/mujoco/blob/3.16.0/doc/XMLreference.rst#tendon-spatial',
        })
    return mappings


class NativeTiltLimits:
    """Bind native tendons and observe angles without correcting engine state."""

    def __init__(self, model, data, descriptions=(), *, prefix='', suffix=''):
        self.model, self.data = model, data
        self.constraints = []
        try:
            for record in descriptions:
                definition = ShaftTiltLimit.from_record(record)
                name = f'{prefix}{definition.name}{suffix}'
                tendon = model.tendon(f'{prefix}{definition.name}_native{suffix}').id
                reference = model.body(f'{prefix}{definition.reference_link}{suffix}').id
                moving = model.body(f'{prefix}{definition.moving_link}{suffix}').id
                self.constraints.append((name, definition, tendon, reference, moving))
        except (KeyError, TypeError, ValueError) as exc:
            raise AssetImportError(f'Native shaft limit binding failed; rebuild MuJoCo resources: {exc}') from exc

    def state(self):
        """Report actual shaft angles, including native numerical penetration."""
        if not self.constraints:
            return {}
        import numpy as np

        require_mujoco().mj_kinematics(self.model, self.data)
        result = {}
        for name, definition, tendon, reference, moving in self.constraints:
            first = self.data.xmat[reference].reshape(3, 3) @ definition.reference_axis
            second = self.data.xmat[moving].reshape(3, 3) @ definition.moving_axis
            angle = math.atan2(float(np.linalg.norm(np.cross(first, second))), float(first @ second))
            if not math.isfinite(angle):
                raise StateValidationError(f'{name}: non-finite shaft orientation')
            result[name] = {'angle_rad': angle, 'max_angle_rad': definition.maximum_rad,
                            'excess_rad': max(0., angle - definition.maximum_rad),
                            'tendon': self.model.tendon(tendon).name}
        return result

    def validate_positions(self):
        """Validate explicit writes only; a native observation is never projected."""
        for name, sample in self.state().items():
            if sample['excess_rad'] > 64 * math.ulp(1.):
                raise StateValidationError(
                    f"{name}: shaft angle {sample['angle_rad']} exceeds requested limit {sample['max_angle_rad']}")
