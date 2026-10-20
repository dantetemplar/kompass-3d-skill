"""Offline fixtures: a source import is deliberately fatal."""
from __future__ import annotations

import skill_paths

import ast
import json
import tempfile
import unittest
from pathlib import Path

from emit import Documentation, NATIVE_SECTION, emit_native, validate_types
from native import NativeModel
from prepare_stubs import generate

SOURCE = '''
import ctypes
raise RuntimeError("SOURCE MUST NOT BE IMPORTED")
from constants import constants as constants
class IAPIObject:
    def __init__(self): pass
    def __init__(self, reference, kompasApp=None): self.reference = reference
class IApplication:
    def __init__(self, kompasApp: int): self.kompasApp = kompasApp
    def GetReference(self): return self.kompasApp
    def GetDocuments(self):
        res = IDocuments(ksapi.IApplication_GetDocuments(self.reference), self)
        res = res if res else None
        return res
class IDocuments(IAPIObject): pass
class IFragmentDocument(IAPIObject): pass
class ILoop(IAPIObject): pass
class IFace(IAPIObject):
    def GetLoops(self):
        ptr = ksapi.IFace_GetLoops(self.reference)
        return FromObjectReferenceVector(self.kompasApp, ptr, ILoop)
class ISketch(IAPIObject):
    def BeginEdit(self, readOnly):
        res = IFragmentDocument(ksapi.ISketch_BeginEdit(self.reference, readOnly))
        return res if res else None
    def GetPoint3D(self, xIn, yIn, xOut, yOut, zOut):
        x = ctypes.c_double(xOut)
        y = ctypes.c_double(yOut)
        z = ctypes.c_double(zOut)
        res = ksapi.ISketch_GetPoint3D(self.reference, xIn, yIn, x, y, z)
        return res, x.value, y.value, z.value
class IExtrusion(IAPIObject):
    def SetProfiles(self, profiles):
        ptr = ToObjectReferenceVector(self.kompasApp, profiles)
        ksapi.IExtrusion_SetProfiles(self.reference, ptr)
class RefString:
    def __init__(self, value: str = ""): pass
    @property
    def value(self) -> str: return ""
class Child(ISketch):
    def BeginEdit(self, readOnly): return super().BeginEdit(readOnly)
def GetKompas():
    app = ksapi.GetKompas()
    return IApplication(app) if app != 0 else None
def Unconfigured(value): return ksapi.Unconfigured(value)
def Encoded(text): return ksapi.Encoded(text.encode('utf-8'))
def StringOutput(text):
    result = RefString(text)
    ksapi.StringOutput(result.ptr_ptr)
    return result.value
Handler = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_int32)
def Callback(callback):
    handler = Handler(callback)
    ksapi.Callback(handler)
def _initialize():
    sk = ksapi.ISketch_GetPoint3D
    sk.restype = ctypes.c_bool
    sk.argtypes = [ctypes.c_uint64, ctypes.c_double, ctypes.c_double, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
    ksapi.ISketch_BeginEdit.restype = ctypes.c_uint64
    ksapi.ISketch_BeginEdit.argtypes = [ctypes.c_uint64, ctypes.c_bool]
    ksapi.Encoded.restype = ctypes.c_int32
    ksapi.Encoded.argtypes = [ctypes.c_char_p]
'''


def metadata_method(name, result, params):
    return {"name_c": name, "return_value": {"type_cpp": result}, "parameters": [{"name": "self", "type_cpp": "ISelfPtr", "in": True}, *[{"name": n, "type_cpp": t, "in": direction} for n, t, direction in params]]}


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / "sdk"
        self.install.mkdir()
        (self.install / "Bin").mkdir()
        (self.install / "Bin/ksapi.py").write_text(SOURCE)
        for module in ("constants", "constants3d"):
            (self.install / f"Bin/{module}.py").write_text('class ' + module + ':\n    VALUE = 42\n    NEGATIVE = -42\n    COMBINED = VALUE | 8\n    NAME = "native"\n')
        self.meta = self.root / "meta.json"
        data = {"ISketch": {"methods": [metadata_method("ISketch_BeginEdit", "IFragmentDocumentPtr", [("readOnly", "bool", "True")]), metadata_method("ISketch_GetPoint3D", "bool", [(n, "double &" if n.endswith("Out") else "double", "False" if n.endswith("Out") else True) for n in ("xIn", "yIn", "xOut", "yOut", "zOut")])]}, "IExtrusion": {"methods": [metadata_method("IExtrusion_SetProfiles", "void", [("profiles", "const std::vector<ILoopPtr> &", "True")])]}}
        self.meta.write_text(json.dumps(data))
        self.docs = self.root / "docs/llm/pages.jsonl"
        self.docs.parent.mkdir(parents=True)
        pages = [{"id": "native", "title": "ISketch.BeginEdit", "symbol": "ISketch.BeginEdit", "section": NATIVE_SECTION, "source_html": "ksapi_isketch_beginedit.html", "title_path": ["ISketch", "BeginEdit"], "content": "Begin editing. Units: мм.", "parent": None, "prev": None, "next": None}, {"id": "com", "title": "ISketch.BeginEdit", "symbol": "ISketch.BeginEdit", "section": "COM", "source_html": "com.html", "content": "WRONG COM"}]
        self.docs.write_text("\n".join(json.dumps(p) for p in pages))

    def model(self):
        model = NativeModel(self.install / "Bin/ksapi.py", self.meta)
        model.analyze_all()
        return model

    def test_exact_native_controls(self):
        methods = self.model().methods
        self.assertEqual(methods["GetKompas"].result, "IApplication | None")
        self.assertEqual(methods["IApplication.__init__"].arguments["kompasApp"], "int")
        self.assertEqual(methods["IApplication.GetReference"].result, "int")
        self.assertEqual(methods["IAPIObject.__init__"].arguments["reference"], "int | IAPIObject")
        self.assertEqual(methods["IApplication.GetDocuments"].result, "IDocuments | None")
        self.assertEqual(methods["ISketch.BeginEdit"].arguments["readOnly"], "bool")
        self.assertEqual(methods["ISketch.BeginEdit"].result, "IFragmentDocument | None")
        self.assertEqual(methods["ISketch.GetPoint3D"].result, "tuple[bool, float, float, float]")
        self.assertEqual(list(methods["ISketch.GetPoint3D"].arguments), ["xIn", "yIn", "xOut", "yOut", "zOut"])
        self.assertEqual(methods["IFace.GetLoops"].result, "list[ILoop]")
        self.assertEqual(methods["IExtrusion.SetProfiles"].result, "None")
        self.assertEqual(methods["IExtrusion.SetProfiles"].arguments["profiles"], "list[ILoop | None]")

    def test_marshalling_and_unconfigured_restype(self):
        model = self.model()
        self.assertEqual(model.methods["Unconfigured"].result, "int")
        self.assertTrue(any(d["symbol"] == "Unconfigured" and "unconfigured" in d["reason"] for d in model.diagnostics))
        self.assertEqual(model.methods["Encoded"].arguments["text"], "str")
        self.assertEqual(model.methods["StringOutput"].result, "str")
        self.assertEqual(model.methods["StringOutput"].arguments["text"], "str")
        self.assertEqual(model.methods["Callback"].arguments["callback"], "Callable[[int], bool]")

    def test_render_generation_and_documentation(self):
        report = generate(self.install, self.docs, self.root / "out", self.meta)
        text = (self.root / "out/ksapi.pyi").read_text()
        tree = ast.parse(text)
        validate_types(text, self.root / "out/ksapi.pyi")
        cls = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "IAPIObject")
        self.assertEqual(len([n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"]), 1)
        self.assertIn("from constants import constants as constants", text)
        self.assertIn("Begin editing.", text)
        self.assertNotIn("WRONG COM", text)
        self.assertIn("@property", text)
        self.assertIn("def Handler(callback: Callable[[int], bool]) -> CFuncPtr", text)
        self.assertIn("ksapi_isketch_beginedit.html", text)
        self.assertIn("VALUE: Literal[42] = 42", (self.root / "out/constants.pyi").read_text())
        self.assertIn("NEGATIVE: Literal[-42] = -42", (self.root / "out/constants.pyi").read_text())
        self.assertIn("COMBINED: int = VALUE | 8", (self.root / "out/constants.pyi").read_text())
        self.assertEqual(report["documentation"]["inherited_matches"], 1)
        self.assertTrue((self.root / "out/report.json").is_file())
        before = {path.name: path.read_bytes() for path in (self.root / "out").iterdir()}
        (self.root / "out/keep.txt").write_text("unrelated")
        generate(self.install, self.docs, self.root / "out", self.meta)
        self.assertEqual(before, {name: (self.root / "out" / name).read_bytes() for name in before})
        self.assertEqual((self.root / "out/keep.txt").read_text(), "unrelated")

    def test_python_argument_and_output_initializer_documentation(self):
        source = self.install / "Bin/ksapi.py"
        source.write_text(SOURCE + '''
def ToObjectReferenceVector(kompasApp, li):
    for apiObj in li:
        if apiObj is not None:
            ksapi.Append(apiObj.reference)
def ReferenceInput(target: ILoop | None):
    ksapi.ReferenceInput(GetReference(target))
''')
        model = self.model()
        docs = Documentation(self.docs)
        text = docs.text("ISketch.GetPoint3D", model, self.root / "out/ksapi.pyi", model.methods["ISketch.GetPoint3D"])
        self.assertIn("- xIn: float; required", text)
        self.assertIn("- xOut: float; required", text)
        self.assertIn("SDK output parameter xOut", text)
        self.assertIn("initializer supplied by the caller", text)
        self.assertIn("ctypes.c_double", text)
        self.assertIn("Python return expression(s): (res, x.value, y.value, z.value)", text)
        text = docs.text("IExtrusion.SetProfiles", model, self.root / "out/ksapi.pyi", model.methods["IExtrusion.SetProfiles"])
        self.assertIn("profiles: list[ILoop | None]", text)
        self.assertIn("converted by ToObjectReferenceVector", text)
        self.assertIn("skips None elements rather than inserting null handles", text)
        self.assertIn("does not infer semantic validity", text)
        reference = docs.text("ReferenceInput", model, self.root / "out/ksapi.pyi", model.methods["ReferenceInput"])
        self.assertIn("GetReference converts None to native handle 0", reference)
        encoded = docs.text("Encoded", model, self.root / "out/ksapi.pyi", model.methods["Encoded"])
        self.assertIn("text: str; required", encoded)
        self.assertIn("encoded to bytes with 'utf-8'", encoded)

    def test_canonical_markdown_identity(self):
        page = json.loads(self.docs.read_text().splitlines()[0])
        page.update(markdown_path="llm/api_objects/native/ISketch.md", markdown_fragment="canonical-beginedit")
        self.docs.write_text(json.dumps(page))
        docs = Documentation(self.docs)
        model = self.model()
        self.assertEqual(docs.markdown_path(page), self.docs.parent.parent / page["markdown_path"])
        text = docs.text("ISketch.BeginEdit", model, self.root / "out/ksapi.pyi", model.methods["ISketch.BeginEdit"])
        self.assertIn("ISketch.md#canonical-beginedit", text)

    def test_categorized_scalar_pointer_discrepancy(self):
        source = self.install / "Bin/ksapi.py"
        source.write_text(SOURCE + '''
def GetColor(): return ksapi.GetColor()
def GetCount(): return ksapi.GetCount()
ksapi.GetColor.restype = ctypes.c_void_p
ksapi.GetCount.restype = ctypes.c_void_p
''')
        metadata = json.loads(self.meta.read_text())
        metadata["scalars"] = {"methods": [metadata_method("GetColor", "Color", []), metadata_method("GetCount", "uint32_t", [])]}
        self.meta.write_text(json.dumps(metadata))
        model = self.model()
        conflicts = {diagnostic["symbol"]: diagnostic for diagnostic in model.diagnostics if "category" in diagnostic}
        self.assertEqual(conflicts["GetColor"]["category"], "color_scalar_configured_as_pointer")
        self.assertEqual(conflicts["GetCount"]["category"], "integer_scalar_configured_as_pointer")
        self.assertEqual(conflicts["GetCount"]["ctypes_restype"], "ctypes.c_void_p")
        self.assertIn("None for zero", conflicts["GetCount"]["explanation"])
        self.assertEqual(model.methods["GetColor"].result, "int | None")
        text = Documentation(self.docs).text("GetColor", model, self.root / "out/ksapi.pyi", model.methods["GetColor"])
        self.assertIn("Marshalling discrepancy:", text)

    def test_effective_defaults_and_property_setter(self):
        source = self.install / "Bin/ksapi.py"
        source.write_text(SOURCE + '''
class Value:
    def __init__(self, old): pass
    def __init__(self, value=3, /, *, enabled=True): pass
    @property
    def number(self) -> int: return 1
    @number.setter
    def number(self, value: int): pass
''')
        model = NativeModel(source, self.meta)
        text = emit_native(model, Documentation(self.docs), self.root / "out/ksapi.pyi")
        self.assertIn("def __init__(self, value: int = 3, /, *, enabled: bool = True)", text)
        self.assertIn("@number.setter", text)
        self.assertIn("def number(self) -> int", text)
        self.assertIn("def number(self, value: int) -> None", text)
        self.assertNotIn("self, old", text)

    def test_missing_docs_actionable(self):
        with self.assertRaisesRegex(FileNotFoundError, "scripts/prepare/prepare_docs.py"):
            Documentation(self.root / "missing.jsonl")

    def test_native_filename_and_ambiguous_mapping(self):
        self.docs.write_text(json.dumps({"id": "old", "title": "BeginEdit", "section": NATIVE_SECTION, "source_html": "ksapi_isketch_beginedit.html", "title_path": [], "content": "Old schema"}))
        docs = Documentation(self.docs)
        self.assertEqual(docs.find("ISketch.BeginEdit", self.model())["id"], "old")
        self.docs.write_text(self.docs.read_text() + "\n" + self.docs.read_text())
        docs = Documentation(self.docs)
        self.assertIsNone(docs.find("ISketch.BeginEdit", self.model()))


if __name__ == "__main__":
    unittest.main()
