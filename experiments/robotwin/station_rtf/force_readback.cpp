// Read-only diagnostic against the exact PhysX 5.6.1 source headers.
#include <cstdint>
#include "NpArticulationLink.h"
#include "ScBodySim.h"
#include "ScSimStateData.h"
extern "C" int probe_force_readback(std::uintptr_t address, float *output) {
  using namespace physx;
  auto *api = static_cast<PxArticulationLink *>(reinterpret_cast<PxActor *>(address));
  auto *link = static_cast<NpArticulationLink *>(api);
  auto *sim = static_cast<Sc::BodySim *>(link->getCore().Sc::ActorCore::getSim());
  if (!sim) return -1;
  auto *state = sim->getSimStateData(false);
  PxVec3 force(0.0f), torque(0.0f);
  if (state) {
    const auto *mod = state->getVelocityModData();
    force = mod->getLinearVelModPerSec() * api->getMass();
    PxQuat q = (api->getGlobalPose()*api->getCMassLocalPose()).q;
    PxVec3 localAccel = q.rotateInv(mod->getAngularVelModPerSec());
    PxVec3 inertia = api->getMassSpaceInertiaTensor();
    torque = q.rotate(PxVec3(localAccel.x*inertia.x,localAccel.y*inertia.y,localAccel.z*inertia.z));
  }
  for (int i=0;i<3;i++) {output[i]=force[i];output[3+i]=torque[i];}
  PxVec3 com=(api->getGlobalPose()*api->getCMassLocalPose()).p;
  for (int i=0;i<3;i++) output[6+i]=com[i];
  return state ? 1 : 0;
}
