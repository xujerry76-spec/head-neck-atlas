set(MODULE_NAME HeadNeckAtlas)
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  AtlasLib/__init__.py
  AtlasLib/catalog.py
  AtlasLib/geometry.py
  AtlasLib/bundle.py
  AtlasLib/inference.py
  AtlasLib/worker.py
  AtlasLib/slicer_bridge.py
  AtlasLib/overlay.py
)
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
)
