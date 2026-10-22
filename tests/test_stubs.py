"""Offline fixtures: a source import is deliberately fatal."""
from __future__ import annotations

import skill_paths

import ast
import json
import tempfile
import unittest
from pathlib import Path

from emit import (
    Documentation,
    NATIVE_SECTION,
    doc_literal,
    emit_constants,
    emit_native,
    merge_com_fallback,
    semantic_documentation,
    validate_types,
)
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
        classes = {c.name: c for c in tree.body if isinstance(c, ast.ClassDef)}
        for name in ("ISketch", "Child"):
            class_doc = ast.get_docstring(classes[name]) or ""
            self.assertIn("Источники SDK:\n- [ISketch](", class_doc)
            self.assertNotIn("переходить по ссылкам", class_doc)
            self.assertNotIn("описания включены", class_doc)
            self.assertIn("[ISketch](", class_doc)
            self.assertEqual(class_doc.count("- ["), 1)
            for method in classes[name].body:
                if isinstance(method, ast.FunctionDef):
                    self.assertNotIn("Источник", ast.get_docstring(method) or "")
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
        self.assertIn("xOut, yOut, zOut: initial value for an SDK output parameter", text)
        self.assertIn("the caller must supply it", text)
        self.assertIn("Returns: (status, xOut, yOut, zOut).", text)
        self.assertNotIn("xIn:", text)
        self.assertNotIn("ctypes.c_double", text)
        self.assertNotIn("return expression", text)
        text = docs.text("IExtrusion.SetProfiles", model, self.root / "out/ksapi.pyi", model.methods["IExtrusion.SetProfiles"])
        self.assertIn("profiles: None elements are skipped, not passed as null handles", text)
        self.assertNotIn("list[ILoop", text)
        self.assertNotIn("semantic validity", text)
        reference = docs.text("ReferenceInput", model, self.root / "out/ksapi.pyi", model.methods["ReferenceInput"])
        self.assertIn("None is passed as native handle 0", reference)
        encoded = docs.text("Encoded", model, self.root / "out/ksapi.pyi", model.methods["Encoded"])
        self.assertIn("text: encoded to bytes with 'utf-8'", encoded)

    def test_simple_method_docstring_contains_no_generated_chatter(self):
        page = {"id": "end", "title": "GetReference - Получить ссылку",
                "symbol": "IApplication.GetReference", "section": NATIVE_SECTION,
                "source_html": "ksapi_iapplication_getreference.html",
                "content": "[Интерфейс...](<webhelp:ksapi_iapplication.html>)\n\n"
                           "Синтаксис KsAPI:\n\nuint64_t GetReference()\n\nПодразделы:\n\n(отсутствуют)"}
        self.docs.write_text(json.dumps(page))
        model = self.model()
        text = Documentation(self.docs).text("IApplication.GetReference", model,
                                             self.root / "out/ksapi.pyi", model.methods["IApplication.GetReference"])
        self.assertEqual(text, "Получить ссылку")
        self.assertNotIn("Local documentation:", text)
        self.assertNotIn("Native documentation:", text)
        for noise in ("Python return", "Python arguments", "Python source", "Native symbols",
                      "Units:", "Подразделы", "Синтаксис", "Интерфейс...", "return expression"):
            self.assertNotIn(noise, text)
        # An unmatched trivial wrapper does not acquire an invented docstring.
        self.assertEqual(Documentation(self.docs).text("Unconfigured", model,
                         self.root / "out/ksapi.pyi", model.methods["Unconfigured"]), "")

    def test_semantic_docs_keep_parameters_notes_examples_units_and_tables(self):
        useful = ("Входные параметры:\n\n| name | meaning |\n| --- | --- |\n"
                  "| angle | угол в градусах |\n\nВозвращаемое значение:\n\nУспешность\n\n"
                  "Примечание:\n\nНе вызывать во время редактирования.\n\n"
                  "```cpp\n    call();\n\n\n    // Подразделы:\n```\n\n"
                  "Особые случаи:\n\nОписание неизвестного генератору раздела.")
        content = ("[Интерфейс...](<webhelp:owner.html>)\n\nСинтаксис KsAPI:\n\n"
                   "void Method(double angle)\n\n" + useful + "\n\nПодразделы:\n\n(отсутствуют)")
        result = semantic_documentation(content)
        self.assertIn("угол в градусах", result)
        self.assertIn("Не вызывать во время редактирования.", result)
        self.assertIn("Особые случаи:\n\nОписание неизвестного генератору раздела.", result)
        self.assertIn("    call();\n\n\n    // Подразделы:", result)
        self.assertNotIn("void Method", result)
        self.assertNotIn("(отсутствуют)", result)
        self.assertNotIn("Интерфейс...", result)
        self.assertEqual(semantic_documentation("Синтаксис KsAPI:\n\nvoid Method()\n\nОсобые случаи:\n\nKeep this."),
                         "Особые случаи:\n\nKeep this.")

    def test_com_fallback_fills_missing_return_and_skips_syntax(self):
        native = ("[Интерфейс...](<webhelp:ksapi_itext.html>)\n\nСинтаксис KsAPI:\n\n"
                  "bool Edit(WindowHandle windowHandle)\n\nПодразделы:\n\n(отсутствуют)")
        com = ("[Интерфейс...](<webhelp:itext.html>)\n\nСинтаксис Automation:\n\n"
               "BOOL Edit( OLE_HANDLE HWnd );\n\nСинтаксис COM:\n\n"
               "HRESULT Edit( OLE_HANDLE HWnd, BOOL * Result );\n\n"
               "Возвращаемое значение:\n\n"
               "| Column 1 | Column 2 |\n| --- | --- |\n"
               "| TRUE | - в случае изменения текста, |\n"
               "| FALSE | - в случае отмены. |\n\n"
               "Входные параметры:\n\n| HWnd | window |\n\n"
               "Подразделы:\n\n(отсутствуют)")
        text, borrowed = merge_com_fallback(native, com)
        self.assertEqual(borrowed, ["Возвращаемое значение:"])
        self.assertIn("в случае изменения текста", text)
        self.assertIn("в случае отмены", text)
        self.assertNotIn("OLE_HANDLE", text)
        self.assertNotIn("Синтаксис", text)
        self.assertNotIn("HWnd", text)
        # Native already documents the return — keep it, ignore COM.
        native_full = native.replace("Подразделы:", "Возвращаемое значение:\n\nУспешность\n\nПодразделы:")
        kept, borrowed = merge_com_fallback(native_full, com)
        self.assertEqual(borrowed, [])
        self.assertIn("Успешность", kept)
        self.assertNotIn("изменения текста", kept)

    def test_com_fallback_applied_in_documentation_text(self):
        pages = [
            {"id": "ksapi_itext_edit", "title": "Edit - Редактировать в окне",
             "symbol": "IText.Edit", "section": NATIVE_SECTION,
             "source_html": "ksapi_itext_edit.html", "title_path": ["IText", "Edit"],
             "content": "Синтаксис KsAPI:\n\nbool Edit(WindowHandle windowHandle)\n\nПодразделы:\n\n(отсутствуют)"},
            {"id": "itext_edit", "title": "Edit - Редактировать в окне",
             "symbol": "IText.Edit", "section": "API интерфейсов. Версия 7",
             "source_html": "itext_edit.html", "title_path": ["IText", "Edit"],
             "content": ("Синтаксис Automation:\n\nBOOL Edit(OLE_HANDLE HWnd);\n\n"
                         "Возвращаемое значение:\n\n"
                         "| TRUE | - в случае изменения текста, |\n"
                         "| FALSE | - в случае отмены. |\n")},
            {"id": "com_noise", "title": "ISketch.BeginEdit", "symbol": "ISketch.BeginEdit",
             "section": "COM", "source_html": "com.html", "content": "WRONG COM"},
        ]
        self.docs.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pages))
        (self.install / "Bin/ksapi.py").write_text(SOURCE + """
class IText(IAPIObject):
  def Edit(self, windowHandle):
    return bool(ksapi.IText_Edit(self.reference, windowHandle))
""")
        meta = json.loads(self.meta.read_text())
        meta["IText"] = {"methods": [metadata_method("IText_Edit", "bool", [("windowHandle", "WindowHandle", "True")])]}
        self.meta.write_text(json.dumps(meta))
        model = self.model()
        docs = Documentation(self.docs)
        text = docs.text("IText.Edit", model, self.root / "out/ksapi.pyi", model.methods["IText.Edit"])
        self.assertIn("Редактировать в окне", text)
        self.assertIn("в случае изменения текста", text)
        self.assertNotIn("OLE_HANDLE", text)
        self.assertNotIn("WRONG COM", text)
        self.assertEqual(docs.stats["com_fallback_symbols"], 1)
        self.assertEqual(docs.stats["com_fallback_sections"], 1)

    def test_canonical_markdown_identity(self):
        page = json.loads(self.docs.read_text().splitlines()[0])
        page.update(markdown_path="llm/api_objects/native/ISketch.md", markdown_fragment="canonical-beginedit")
        self.docs.write_text(json.dumps(page))
        docs = Documentation(self.docs)
        model = self.model()
        self.assertEqual(docs.markdown_path(page), self.docs.parent.parent / page["markdown_path"])
        text = docs.text("ISketch.BeginEdit", model, self.root / "out/ksapi.pyi", model.methods["ISketch.BeginEdit"])
        self.assertNotIn("ISketch.md", text)
        sources = docs.class_sources("ISketch", self.root / "out/ksapi.pyi")
        self.assertIn("[ISketch](../docs/llm/api_objects/native/ISketch.md)", sources)
        self.assertNotIn("#canonical-beginedit", sources)

    def test_class_sources_deduplicate_documents_and_keep_inherited_sources(self):
        (self.install / "Bin/ksapi.py").write_text(SOURCE.replace(
            "class ISketch(IAPIObject):", "class ISketch(IAPIObject):\n    def __init__(self): pass"))
        pages = [
            {"symbol": symbol, "title": symbol, "section": NATIVE_SECTION,
             "source_html": "ksapi_" + symbol.lower().replace(".", "_") + ".html",
             "markdown_path": f"llm/{owner}.md", "content": "SDK explanation"}
            for symbol, owner in (("ISketch", "ISketch"), ("ISketch.BeginEdit", "ISketch"),
                                  ("ISketch.GetPoint3D", "ISketch"), ("IAPIObject.__init__", "IAPIObject"))
        ]
        self.docs.write_text("\n".join(json.dumps(page) for page in pages))
        tree = ast.parse(emit_native(self.model(), Documentation(self.docs), self.root / "out/ksapi.pyi"))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        sources = ast.get_docstring(classes["ISketch"]) or ""
        self.assertEqual(sources.count("[ISketch]("), 1)
        self.assertEqual(sources.count("[IAPIObject]("), 1)
        self.assertEqual(sources.count("- ["), 2)
        child_sources = ast.get_docstring(classes["Child"]) or ""
        self.assertEqual(child_sources.count("[ISketch]("), 1)

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

    def test_constant_attribute_docs_match_name_and_value(self):
        source = self.install / "Bin/constants.py"
        source.write_text('''class constants:
    VALUE = 42  # Short installed description
    NEGATIVE = -42  # Negative
    OTHER = 7  # Keep installed meaning
    AMBIGUOUS = 8  # Installed description is unambiguous
    UNDOCUMENTED = 9
    TEXT = "# not a comment"  # A "quote" and C:\\path
''')
        pages = [
            {"section": "Константы API", "markdown_path": "llm/constants.md",
             "content": '| VALUE | 42 | SDK "description" with \\| separator |\n'
                        '| NEGATIVE | -42 | Negative from SDK |\n'
                        '| OTHER | 99 | Wrong value |\n'
                        '| AMBIGUOUS | 8 | First meaning |'},
            {"section": "Константы API", "markdown_path": "llm/constants.md",
             "content": '| VALUE | 42 | SDK "description" with \\| separator |\n'
                        '| AMBIGUOUS | 8 | Second meaning |'},
            {"section": "COM", "content": "| OTHER | 7 | Unrelated documentation |"},
        ]
        self.docs.write_text("\n".join(json.dumps(page) for page in pages))
        docs = Documentation(self.docs)
        text = emit_constants(source, docs, self.root / "out/constants.pyi")
        body = ast.parse(text).body[-1].body
        descriptions = {node.target.id: body[index + 1].value.value
                        for index, node in enumerate(body[:-1])
                        if isinstance(node, ast.AnnAssign) and isinstance(body[index + 1], ast.Expr)}
        self.assertEqual(descriptions["VALUE"], 'SDK "description" with | separator')
        self.assertEqual(descriptions["NEGATIVE"], "Negative from SDK")
        self.assertEqual(descriptions["OTHER"], "Keep installed meaning")
        self.assertEqual(descriptions["AMBIGUOUS"], "Installed description is unambiguous")
        self.assertEqual(descriptions["TEXT"], 'A "quote" and C:\\path')
        self.assertNotIn("UNDOCUMENTED", descriptions)
        self.assertEqual(text.count("[Константы API]("), 1)
        self.assertEqual(docs.stats["constants_from_sdk"], 2)
        self.assertEqual(docs.stats["constants_from_wrapper_comments"], 3)
        self.assertEqual(docs.stats["constants_without_docs"], 1)
        for line in text.splitlines():
            if line.strip().startswith('"') and not line.strip().startswith('"""'):
                self.assertTrue(line.endswith('"'))
                self.assertFalse(line.endswith('"""'))

    def test_enum_aliases_mapping_and_explicit_input_binding(self):
        source = self.install / "Bin/ksapi.py"
        source.write_text(SOURCE + '''
class EnumClient:
    def SetKind(self, value): ksapi.EnumClient_SetKind(self.kompasApp.GetReference(), self.reference, value)
    def SetMask(self, value): ksapi.EnumClient_SetMask(self.reference, value)
    def SetUnrelated(self, value): ksapi.EnumClient_SetUnrelated(self.reference, value)
    def GetKind(self): return ksapi.EnumClient_GetKind(self.reference)
    def Transform(self, value):
        value = value + 1
        ksapi.EnumClient_SetKind(self.kompasApp.GetReference(), self.reference, value)
ksapi.EnumClient_SetKind.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int32]
ksapi.EnumClient_SetMask.argtypes = [ctypes.c_uint64, ctypes.c_int32]
ksapi.EnumClient_SetUnrelated.argtypes = [ctypes.c_uint64, ctypes.c_int32]
ksapi.EnumClient_GetKind.restype = ctypes.c_int32
''')
        data = json.loads(self.meta.read_text())
        data["EnumClient"] = {"methods": [
            metadata_method("EnumClient_SetKind", "void", [("value", "KindEnum", True)]),
            metadata_method("EnumClient_SetMask", "void", [("value", "MaskEnum", True)]),
            metadata_method("EnumClient_SetUnrelated", "void", [("value", "int32_t", True)]),
            metadata_method("EnumClient_GetKind", "KindEnum", []),
        ]}
        self.meta.write_text(json.dumps(data))
        (self.install / "Bin/constants.py").write_text('class constants:\n    FIRST = 0\n    SECOND = 1\n    BIT_A = 1\n    BIT_B = 2\n    BIT_C = 4\n')
        pages = [
            {"section": "Константы API", "title": "KindEnum - Тип объекта",
             "content": "| FIRST | 0 | Первый |\n| SECOND | 1 | Второй |"},
            {"section": "Константы API", "title": "MaskEnum - Битовая маска",
             "content": "| BIT_A | 1 | A |\n| BIT_B | 2 | B |\n| BIT_C | 4 | C |"},
        ]
        self.docs.write_text("\n".join(json.dumps(page) for page in pages))
        report = generate(self.install, self.docs, self.root / "out", self.meta)
        text = (self.root / "out/ksapi.pyi").read_text()
        self.assertNotIn("from constants import KindEnum", text)
        self.assertIn("def SetKind(self, value: Literal[0, 1])", text)
        self.assertIn("Допустимые значения value (KindEnum):\n        0 — FIRST: Первый\n        1 — SECOND: Второй", text)
        self.assertIn("def SetMask(self, value: int)", text)
        self.assertIn("def SetUnrelated(self, value: int)", text)
        self.assertIn("def GetKind(self) -> int", text)
        self.assertNotIn("def Transform(self, value: KindEnum)", text)
        constants = (self.root / "out/constants.pyi").read_text()
        self.assertNotIn("KindEnum: TypeAlias", constants)
        self.assertTrue(report["enum_aliases"]["KindEnum"]["inline"])
        self.assertEqual(report["documentation"]["enum_inline_domains"], 1)
        self.assertIn("MaskEnum: TypeAlias = int", constants)
        self.assertEqual(report["documentation"]["enum_input_parameters"], 1)
        self.assertEqual(report["enum_bindings"][0]["symbol"], "EnumClient.SetKind")

    def test_enum_shared_by_methods_retains_alias(self):
        source = self.install / "Bin/ksapi.py"
        source.write_text(SOURCE + '''
class EnumClient:
    def SetKind(self, value): ksapi.EnumClient_SetKind(self.reference, value)
    def Another(self, value): ksapi.EnumClient_SetKind(self.reference, value)
ksapi.EnumClient_SetKind.argtypes = [ctypes.c_uint64, ctypes.c_int32]
''')
        data = json.loads(self.meta.read_text())
        data["EnumClient"] = {"methods": [metadata_method("EnumClient_SetKind", "void", [("value", "KindEnum", True)])]}
        self.meta.write_text(json.dumps(data))
        (self.install / "Bin/constants.py").write_text("class constants:\n    FIRST = 0\n    SECOND = 1\n")
        self.docs.write_text(json.dumps({"section": "Константы API", "title": "KindEnum - Тип объекта",
                                         "content": "| FIRST | 0 | Первый |\n| SECOND | 1 | Второй |"}))
        report = generate(self.install, self.docs, self.root / "out", self.meta)
        text = (self.root / "out/ksapi.pyi").read_text()
        self.assertIn("from constants import KindEnum", text)
        self.assertIn("def SetKind(self, value: KindEnum)", text)
        self.assertIn("def Another(self, value: KindEnum)", text)
        self.assertNotIn("Допустимые значения value (KindEnum)", text)
        self.assertFalse(report["enum_aliases"]["KindEnum"]["inline"])
        constants = (self.root / "out/constants.pyi").read_text()
        self.assertIn("KindEnum: TypeAlias = Literal[0, 1]", constants)
        self.assertIn('"""Тип объекта\n\n0 — FIRST: Первый\n1 — SECOND: Второй\n"""', constants)

    def test_single_method_multiple_enum_parameters_inline_and_class_sources(self):
        source = self.install / "Bin/ksapi.py"
        source.write_text(SOURCE + '''
class EnumClient:
    def SetPair(self, first, second): ksapi.EnumClient_SetPair(self.reference, first, second)
ksapi.EnumClient_SetPair.argtypes = [ctypes.c_uint64, ctypes.c_int32, ctypes.c_int32]
''')
        data = json.loads(self.meta.read_text())
        data["EnumClient"] = {"methods": [metadata_method("EnumClient_SetPair", "void", [
            ("first", "KindEnum", True), ("second", "KindEnum", True)])]}
        self.meta.write_text(json.dumps(data))
        (self.install / "Bin/constants.py").write_text("class constants:\n    FIRST = 0\n    SECOND = 1\n")
        self.docs.write_text(json.dumps({"section": "Константы API", "title": "KindEnum - Тип объекта",
                                         "markdown_path": "llm/kind.md", "content": "| FIRST | 0 | Первый |\n| SECOND | 1 | Второй |"}))
        report = generate(self.install, self.docs, self.root / "out", self.meta)
        tree = ast.parse((self.root / "out/ksapi.pyi").read_text())
        client = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EnumClient")
        method = next(node for node in client.body if isinstance(node, ast.FunctionDef))
        for arg in method.args.args[1:]:
            self.assertEqual(ast.unparse(arg.annotation), "Literal[0, 1]")
            self.assertIn(f"Допустимые значения {arg.arg} (KindEnum):", ast.get_docstring(method))
        self.assertIn("Источники SDK:", ast.get_docstring(client))
        self.assertIn("kind.md)", ast.get_docstring(client))
        self.assertNotIn("Источники SDK:", ast.get_docstring(method))
        self.assertEqual(report["documentation"]["enum_inline_domains"], 1)
        self.assertEqual(report["documentation"]["enum_input_parameters"], 2)
        self.assertNotIn("KindEnum: TypeAlias", (self.root / "out/constants.pyi").read_text())

    def test_single_function_enum_inlines_in_function_docstring(self):
        source = self.install / "Bin/ksapi.py"
        source.write_text(SOURCE + '''
def SetKind(value): ksapi.SetKind(value)
ksapi.SetKind.argtypes = [ctypes.c_int32]
''')
        data = json.loads(self.meta.read_text())
        data["SetKind"] = {"name_c": "SetKind", "return_value": {"type_cpp": "void"},
                           "parameters": [{"name": "value", "type_cpp": "KindEnum", "in": True}]}
        self.meta.write_text(json.dumps(data))
        (self.install / "Bin/constants.py").write_text("class constants:\n    FIRST = 0\n    SECOND = 1\n")
        self.docs.write_text(json.dumps({"section": "Константы API", "title": "KindEnum - Kind",
                                         "content": "| FIRST | 0 | First |\n| SECOND | 1 | Second |"}))
        generate(self.install, self.docs, self.root / "out", self.meta)
        tree = ast.parse((self.root / "out/ksapi.pyi").read_text())
        method = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "SetKind")
        self.assertEqual(ast.unparse(method.args.args[0].annotation), "Literal[0, 1]")
        self.assertIn("Допустимые значения value (KindEnum):\n0 — FIRST: First\n1 — SECOND: Second", ast.get_docstring(method))
        self.assertNotIn("KindEnum: TypeAlias", (self.root / "out/constants.pyi").read_text())

    def test_enum_rejects_entire_untrustworthy_table(self):
        (self.install / "Bin/constants.py").write_text("class constants:\n    FIRST = 0\n    SECOND = 1\n")
        tables = {
            "drift": "| FIRST | 0 | First |\n| SECOND | 2 | Wrong |",
            "missing": "| FIRST | 0 | First |\n| SECOND | | Missing |",
            "anonymous": "| FIRST | 0 | First |\n| | 1 | Unnamed |",
            "malformed": "| FIRST | 0 | First |\n| SECOND | 1, | Malformed |",
            "unknown": "| FIRST | 0 | First |\n| UNKNOWN | 1 | Missing constant |",
            "conflicting": "| FIRST | 0 | First |\n| FIRST | 1 | Conflicting |",
            "operands": "| FIRST | 0 | First |\n| SECOND | 0x1 | 0x8 | Composite |",
        }
        for case, content in tables.items():
            with self.subTest(case=case):
                self.docs.write_text(json.dumps({"section": "Константы API", "title": "KindEnum - Kind", "content": content}))
                report = generate(self.install, self.docs, self.root / "out", self.meta)
                self.assertNotIn("KindEnum", report["enum_aliases"])
                self.assertIn("KindEnum", report["enum_rejections"])
                self.assertNotIn("KindEnum: TypeAlias", (self.root / "out/constants.pyi").read_text())

    def test_linked_usage_vetoes_closed_enum_and_evaluates_constants(self):
        (self.install / "Bin/constants.py").write_text("class constants:\n    FIRST = 0\n    SECOND = FIRST | 3\n")
        pages = [{"section": "Константы API", "title": "KindEnum - Kind",
                  "content": "| FIRST | 0 | First |\n| SECOND | 3 | Second |"},
                 {"section": "Automation", "content": "Допускается комбинация значений [KindEnum](<webhelp:kind.html>)."}]
        self.docs.write_text("\n".join(json.dumps(page) for page in pages))
        report = generate(self.install, self.docs, self.root / "out", self.meta)
        self.assertEqual(report["enum_aliases"]["KindEnum"]["values"], [0, 3])
        self.assertFalse(report["enum_aliases"]["KindEnum"]["closed"])
        self.assertIn("KindEnum: TypeAlias = int", (self.root / "out/constants.pyi").read_text())

    def test_single_line_docstrings_use_one_pair_of_double_quotes(self):
        text = 'Описание с "кавычками" и C:\\path'
        literal = doc_literal(text, "    ")
        self.assertEqual(literal, ["    " + json.dumps(text, ensure_ascii=False)])
        self.assertEqual(ast.literal_eval(literal[0].strip()), text)

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
