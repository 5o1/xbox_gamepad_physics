// Read-only diagnostic adapter for the installed SAPIEN/PhysX public C++ API.
// pybind11's conduit protocol handles the wheel's different binding internals.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/conduit/pybind11_conduit_v1.h>
#include <sapien/physx/collision_shape.h>
#include <sapien/physx/rigid_component.h>
#include <sapien/physx/physx_system.h>
#include <cstdint>
#include <stdexcept>
namespace py = pybind11;
using Shape = sapien::physx::PhysxCollisionShapeTriangleMesh;
template <typename T> T &native(const py::object &object) {
  auto pointer = pybind11_conduit_v1::get_type_pointer_ephemeral<T>(object.ptr());
  if (!pointer) throw py::error_already_set();
  return *pointer;
}
PYBIND11_MODULE(sapien_sdf_bridge, m) {
  m.def("shape_info", [](py::object object) {
    auto &s = native<Shape>(object);
    auto mesh = s.getMesh();
    auto px = mesh->getPxMesh();
    physx::PxU32 x=0,y=0,z=0;
    px->getSDFDimensions(x,y,z);
    py::dict r;
    r["has_cooked_sdf"] = px->getSDF() != nullptr;
    r["sdf_enabled"] = mesh->getSDFEnabled();
    r["spacing_m"] = mesh->getSDFSpacing();
    r["subgrid_size"] = mesh->getSDFSubgridSize();
    r["dense_sdf_dimensions"] = std::vector<unsigned>{x,y,z};
    r["internal_shape_id"] = s.getPxShape()->getInternalShapeIndex();
    r["header_physx_version"] = std::vector<int>{PX_PHYSICS_VERSION_MAJOR,PX_PHYSICS_VERSION_MINOR,PX_PHYSICS_VERSION_BUGFIX};
    return r;
  });
  m.def("attach_shared_clone", [](py::object source_object, py::object body_object) {
    auto &source = native<Shape>(source_object);
    auto &body = native<sapien::physx::PhysxRigidBaseComponent>(body_object);
    body.attachCollision(source.clone());
  });
  m.def("same_cooked_mesh", [](py::object a_object, py::object b_object) {
    auto &a = native<Shape>(a_object);
    auto &b = native<Shape>(b_object);
    return a.getMesh()->getPxMesh() == b.getMesh()->getPxMesh();
  });
  m.def("sample", [](py::object system_object, std::uintptr_t ids,
                     std::uintptr_t points, std::uintptr_t counts, unsigned n,
                     std::uintptr_t output) {
    auto scene = native<sapien::physx::PhysxSystem>(system_object).getPxScene();
    if (!(scene->getFlags() & physx::PxSceneFlag::eENABLE_GPU_DYNAMICS))
      throw std::runtime_error("SDF evaluation requires the separate GPU query scene");
    scene->evaluateSDFDistances(reinterpret_cast<const physx::PxU32*>(ids),1,
      reinterpret_cast<const physx::PxVec4*>(points),reinterpret_cast<const physx::PxU32*>(counts),n,
      reinterpret_cast<physx::PxVec4*>(output));
  });
}
