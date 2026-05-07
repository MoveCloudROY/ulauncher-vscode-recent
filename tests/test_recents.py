import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"


def stub_module(name):
	module = types.ModuleType(name)
	sys.modules[name] = module
	return module


def stub_dependencies():
	module_names = [
		"ulauncher",
		"ulauncher.api",
		"ulauncher.api.client",
		"ulauncher.api.client.Extension",
		"ulauncher.api.client.EventListener",
		"ulauncher.api.shared",
		"ulauncher.api.shared.event",
		"ulauncher.api.shared.item",
		"ulauncher.api.shared.item.ExtensionResultItem",
		"ulauncher.api.shared.item.ExtensionSmallResultItem",
		"ulauncher.api.shared.action",
		"ulauncher.api.shared.action.RenderResultListAction",
		"ulauncher.api.shared.action.HideWindowAction",
		"ulauncher.api.shared.action.ExtensionCustomAction",
		"fuzzywuzzy",
	]
	for name in module_names:
		if name not in sys.modules:
			stub_module(name)

	class StubExtension(object):
		def __init__(self):
			pass

		def subscribe(self, *args):
			pass

		def run(self):
			pass

	class StubEventListener(object):
		pass

	class StubAction(object):
		def __init__(self, *args, **kwargs):
			pass

	sys.modules["ulauncher.api.client.Extension"].Extension = StubExtension
	sys.modules["ulauncher.api.client.EventListener"].EventListener = StubEventListener
	sys.modules["ulauncher.api.shared.event"].KeywordQueryEvent = object
	sys.modules["ulauncher.api.shared.event"].ItemEnterEvent = object
	sys.modules["ulauncher.api.shared.event"].PreferencesEvent = object
	sys.modules["ulauncher.api.shared.event"].PreferencesUpdateEvent = object
	sys.modules[
		"ulauncher.api.shared.item.ExtensionResultItem"
	].ExtensionResultItem = StubAction
	sys.modules[
		"ulauncher.api.shared.item.ExtensionSmallResultItem"
	].ExtensionSmallResultItem = StubAction
	sys.modules[
		"ulauncher.api.shared.action.RenderResultListAction"
	].RenderResultListAction = StubAction
	sys.modules[
		"ulauncher.api.shared.action.HideWindowAction"
	].HideWindowAction = StubAction
	sys.modules[
		"ulauncher.api.shared.action.ExtensionCustomAction"
	].ExtensionCustomAction = StubAction
	sys.modules["fuzzywuzzy"].process = types.SimpleNamespace(extract=lambda *args, **kwargs: [])
	sys.modules["fuzzywuzzy"].fuzz = types.SimpleNamespace(partial_ratio=None)


def load_main():
	stub_dependencies()
	spec = importlib.util.spec_from_file_location("ulauncher_vscode_recent", MAIN)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def create_state_db(path, entries=None):
	con = sqlite3.connect(str(path))
	try:
		cur = con.cursor()
		cur.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
		if entries is not None:
			cur.execute(
				"INSERT INTO ItemTable VALUES (?, ?)",
				("history.recentlyOpenedPathsList", json.dumps({"entries": entries})),
			)
		con.commit()
	finally:
		con.close()


class RecentsTest(unittest.TestCase):
	def test_uses_shared_state_database_before_legacy_fallbacks(self):
		module = load_main()
		with tempfile.TemporaryDirectory() as temp_dir:
			root = pathlib.Path(temp_dir)
			shared_root = root / "sharedStorage"
			shared_root.mkdir()
			shared_db = shared_root / "state.vscdb"
			current_db = root / "state.vscdb"
			storage_json = root / "storage.json"

			create_state_db(shared_db, [{"folderUri": "file:///tmp/shared-project"}])
			create_state_db(current_db)
			storage_json.write_text(
				json.dumps(
					{
						"profileAssociations": {
							"workspaces": {"file:///tmp/profile-project": "__default__profile__"}
						}
					}
				)
			)

			code = module.Code.__new__(module.Code)
			code.installed_path = pathlib.Path("/usr/bin/code")
			code.config_path = root
			code.shared_state_db = shared_db
			code.global_state_db = current_db
			code.storage_json = storage_json

			self.assertEqual(
				code.get_recents(),
				[
					{
						"uri": "file:///tmp/shared-project",
						"label": "shared-project",
						"icon": "folder",
						"option": "--folder-uri",
					}
				],
			)

	def test_uses_backup_state_database_when_current_database_has_no_recent_paths(self):
		module = load_main()
		with tempfile.TemporaryDirectory() as temp_dir:
			root = pathlib.Path(temp_dir)
			current_db = root / "state.vscdb"
			backup_db = root / "state.vscdb.backup"
			storage_json = root / "storage.json"

			create_state_db(current_db)
			create_state_db(backup_db, [{"folderUri": "file:///tmp/project"}])
			storage_json.write_text(json.dumps({"profileAssociations": {}}))

			code = module.Code.__new__(module.Code)
			code.installed_path = pathlib.Path("/usr/bin/code")
			code.config_path = root
			code.global_state_db = current_db
			code.storage_json = storage_json

			self.assertEqual(
				code.get_recents(),
				[
					{
						"uri": "file:///tmp/project",
						"label": "project",
						"icon": "folder",
						"option": "--folder-uri",
					}
				],
			)

	def test_uses_profile_associations_when_recent_paths_are_absent(self):
		module = load_main()
		with tempfile.TemporaryDirectory() as temp_dir:
			root = pathlib.Path(temp_dir)
			current_db = root / "state.vscdb"
			backup_db = root / "state.vscdb.backup"
			storage_json = root / "storage.json"

			create_state_db(current_db)
			create_state_db(backup_db)
			storage_json.write_text(
				json.dumps(
					{
						"profileAssociations": {
							"workspaces": {
								"file:///tmp/project": "__default__profile__",
								"file:///tmp/demo.code-workspace": "__default__profile__",
							}
						}
					}
				)
			)

			code = module.Code.__new__(module.Code)
			code.installed_path = pathlib.Path("/usr/bin/code")
			code.config_path = root
			code.global_state_db = current_db
			code.storage_json = storage_json

			self.assertEqual(
				code.get_recents(),
				[
					{
						"uri": "file:///tmp/project",
						"label": "project",
						"icon": "folder",
						"option": "--folder-uri",
					},
					{
						"uri": "file:///tmp/demo.code-workspace",
						"label": "demo.code-workspace",
						"icon": "workspace",
						"option": "--file-uri",
					},
				],
			)


if __name__ == "__main__":
	unittest.main()
