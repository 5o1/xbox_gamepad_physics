# Scope

This independent repository owns Xbox gamepad physical assets and validation.
Do not modify sibling game RL, VLA, or original asset directories as an implicit
part of work here. No hardware IO or physical robot commands.

Research primary documentation before making new design choices. Every adopted
physical parameter needs traceable evidence with units, source applicability,
derivation, and uncertainty. Validate at subsystem boundaries in proportion to
risk; do not create a separate harness for every field or for an unimplemented
future schema. Keep unsupported values null with an explanation; never silently
fill them with simulator defaults.
Distinguish geometry previews from dynamics/contact validation and RL results.

Distribute only Xbox One S model assets. Other controller models remain archived
on the GPU node. Preserve historical reports and provenance records in this repo.

Geometry identity is a prerequisite, not a deferred warning. The archived Casper
Xbox mesh was rejected only as a 1708 match. It remains an archived Xbox Series
X|S / 1914 appearance candidate, inferred from rendered features, not a verified
mechanical replica. Do not register 1708 mechanics to it. Its archive retains the intact
44-part original for 1914; do not reuse the 1708-width/Share-removed derivative
as a validated 1914 asset. Preserve both for provenance.
For every proposed replacement, download the actual file, render its front view,
and present it to the user for confirmation before adoption. Website promotional
images, filenames, width scaling and software tests do not establish identity.
Do not substitute unrelated viewer features for resolving a failed geometry gate.

Keep large meshes, datasets, weights and intermediates on the GPU node. Respect
upstream licenses and keep source files unchanged. Downloads must follow the
user's real-IP direct-first networking requirement, with port FALLBACK_PROXY_PORT proxy only
as fallback after verified direct failure.
