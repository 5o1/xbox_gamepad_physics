// Diagnostic adapter for the pinned PhysX 5.6.1 SDK. No SAPIEN rebuild.
// Use only while the owning scene is idle, with SAPIEN's live PxActor pointer.
#include <cstdint>
#include <PxActor.h>
#include <PxScene.h>

extern "C" std::uint32_t station_rtf_batch(std::uintptr_t actor,
                                          std::uint32_t value) {
  auto *scene = reinterpret_cast<physx::PxActor *>(actor)->getScene();
  if (value != 0) {
    scene->setSolverArticulationBatchSize(value);
  }
  return scene->getSolverArticulationBatchSize();
}
