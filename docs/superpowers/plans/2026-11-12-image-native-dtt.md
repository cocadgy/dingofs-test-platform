# Image-native DTT installation and execution

User approved: build platform interfaces/framework/cases into a fixed DTT image; install only image and launchers; catalog/preflight/execution bind the same image source hashes. Proceed without intermediate questions, per earlier execution preference.

## Design
- Preserve directory-based packages for compatibility; add an explicit image-backed automatic installation mode for DTT.
- Build a local immutable image on the existing pinned tools base. Replace the entire old integration tree, include reviewed complete source and entrypoint, and embed a small launcher package under /opt/dtt-platform. No registry publish and no secret output.
- Image package metadata image-manifest.json contains tool, entrypoint, architecture, host launcher hashes, source_manifest, source_aliases, functional_features, and source_location=image. Image ID is attached only after Docker build (avoid a self-referential digest).
- Target installer obtains this package with docker create/cp/rm, verifies image ID and files, generates standard capability and wrapper metadata. It does not SCP source or test cases. Existing manifest and immutable installation semantics remain.
- Host capability verification checks launcher hashes and pinned image source hashes via a read-only/no-network container. Execution mounts only runtime metadata/context/outputs, NOT the integration tree. Container verifies its own /dingofs-integration-test before setup.
- Platform catalog uses the reviewed source mirror that has exactly the same source manifest as the built image. Existing preflight rejects any drift; no weakened checks.
- Same-host deployment uses the already-built immutable image. Do not export/load the same image back to itself. Other machines resolve the specified image before package extraction.

## Tasks / ownership
1. DTT image builder: Dockerfile.platform, scripts/build_platform_image.py, tests. Build context excludes git/caches and includes exact reviewed source; aliases preserved; emit image-manifest.json. Image verification CLI consumes this metadata. Do not edit functional_runtime.py.
2. Platform image installer: optional API source_mode=image for automatic DTT only, routes options, automatic dispatch, image helper with extraction and metadata validation, functional_bundle/install_helper support. Existing mode unchanged. Tests first.
3. DTT runtime: functional_runtime.py image source capability and no source overlay in guided/legacy launch. --image-source-manifest command hashes actual image tree with declared aliases. Container verification uses actual /dingofs-integration-test. Tests first.
4. Integrate, test both modes including actual no-network image. Review. Commit locally and deploy API. Reconcile only interrupted prior install after process/handle verification. Install image-mode no_timeout=true once; verify completed capability and read-only platform preflight.

## Validation
Regression tests must fail before implementation. Cover omitted/invalid mode, changed image source, aliases, small launcher-only package, no integration-tree bind mount, response-size handling, preserved old mode, failed install retaining lease and unchanged active installation. Use isolated test DB. Known unrelated baseline backend failures remain outside this change; do not conceal them.

## Non-goals
No changes to main branch or registry; no filesystem test execution during installation; no deletion of previous installation or failed staging; no new cluster or filesystem.

## Implementation and deployment evidence
- Implemented explicit image mode, target-only package extraction, immutable image/source verification, and image-backed guided/legacy execution. Image root is read-only with writable output/home/tmp mounts. Legacy custom environments allow only the selected new generated YAML; original manifest files remain immutable.
- Local regression: platform installer/API/SSH tests 42 passed; DTT focused runtime/builder/plan/environment tests 46 passed and 9 subtests passed. Wider DTT suite has two pre-existing localhost report-server readiness failures (242 passed, 7 skipped); no claim of a fully green suite.
- Real derived image source verification matched all 1,042 source files; immutable image ID sha256:8df1dfd4d304fe678b12cfae56fc279bd0bec661a76e4527dc62dd199e9d39d1.
- API image dingofs-test-platform-api:image-native-20261112 deployed; readiness returned guided_functional=ready. No schema change or web redeploy.
- Interrupted prior installation verified with zero matching processes/open handles and unchanged previous command link; its two leases released using verified recovery, staging retained.
- New image-mode installation 47e6f06a-fb95-445d-8b05-5e4605020bcd succeeded at 100% in approximately 8 seconds, with no total timeout. Active command independently reports protocol v2 and the expected image/source manifest. No host integration-test directory exists in the new package.
- No registry push, no filesystem workload, no previous installation/staging deletion.
