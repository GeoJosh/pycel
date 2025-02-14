import json
import os
import shutil
from unittest import mock

import pytest
from pycel.excelcompiler import _Cell, _CellRange, ExcelCompiler
from pycel.excelformula import FormulaParserError, UnknownFunction
from pycel.excelutil import (
    AddressCell,
    AddressRange,
    flatten,
    list_like,
    NULL_ERROR,
)
from pycel.excelwrapper import ExcelWrapper


# ::TODO:: need some rectangular ranges for testing


def test_end_2_end(excel, fixture_xls_path):
    # load & compile the file to a graph, starting from D1
    for excel_compiler in (ExcelCompiler(excel=excel),
                           ExcelCompiler(fixture_xls_path)):

        # test evaluation
        assert -0.02286 == round(excel_compiler.evaluate('Sheet1!D1'), 5)

        excel_compiler.set_value('Sheet1!A1', 200)
        assert -0.00331 == round(excel_compiler.evaluate('Sheet1!D1'), 5)


def test_no_sheet_given(excel_compiler):
    sh1_value = excel_compiler.evaluate('Sheet1!A1')

    excel_compiler.excel.set_sheet('Sheet1')
    value = excel_compiler.evaluate('A1')
    assert sh1_value == value

    excel_compiler.excel.set_sheet('Sheet2')
    value = excel_compiler.evaluate('A1')
    assert sh1_value != value


def test_round_trip_through_json_yaml_and_pickle(
        excel_compiler, fixture_xls_path):
    excel_compiler.evaluate('Sheet1!D1')
    excel_compiler.extra_data = {1: 3}
    excel_compiler.to_file(file_types=('pickle', ))
    excel_compiler.to_file(file_types=('yml', ))
    excel_compiler.to_file(file_types=('json', ))

    # read the spreadsheet from json, yaml and pickle
    excel_compiler_json = ExcelCompiler.from_file(
        excel_compiler.filename + '.json')
    excel_compiler_yaml = ExcelCompiler.from_file(
        excel_compiler.filename + '.yml')
    excel_compiler = ExcelCompiler.from_file(excel_compiler.filename)

    # test evaluation
    assert -0.02286 == round(excel_compiler_json.evaluate('Sheet1!D1'), 5)
    assert -0.02286 == round(excel_compiler_yaml.evaluate('Sheet1!D1'), 5)
    assert -0.02286 == round(excel_compiler.evaluate('Sheet1!D1'), 5)

    excel_compiler_json.set_value('Sheet1!A1', 200)
    assert -0.00331 == round(excel_compiler_json.evaluate('Sheet1!D1'), 5)

    excel_compiler_yaml.set_value('Sheet1!A1', 200)
    assert -0.00331 == round(excel_compiler_yaml.evaluate('Sheet1!D1'), 5)

    excel_compiler.set_value('Sheet1!A1', 200)
    assert -0.00331 == round(excel_compiler.evaluate('Sheet1!D1'), 5)


def test_filename_ext(excel_compiler, fixture_xls_path):
    excel_compiler.evaluate('Sheet1!D1')
    excel_compiler.extra_data = {1: 3}
    pickle_name = excel_compiler.filename + '.pkl'
    yaml_name = excel_compiler.filename + '.yml'
    json_name = excel_compiler.filename + '.json'

    for name in (pickle_name, yaml_name, json_name):
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass

    excel_compiler.to_file(excel_compiler.filename)
    excel_compiler.to_file(json_name, file_types=('json', ))

    assert os.path.exists(pickle_name)
    assert os.path.exists(yaml_name)
    assert os.path.exists(json_name)


def test_filename_extension_errors(excel_compiler, fixture_xls_path):
    with pytest.raises(ValueError, match='Unrecognized file type'):
        ExcelCompiler.from_file(excel_compiler.filename + '.xyzzy')

    with pytest.raises(ValueError, match='Only allowed one '):
        excel_compiler.to_file(file_types=('pkl', 'pickle'))

    with pytest.raises(ValueError, match='Only allowed one '):
        excel_compiler.to_file(file_types=('pkl', 'yml', 'json'))

    with pytest.raises(ValueError, match='Unknown file types: pkly'):
        excel_compiler.to_file(file_types=('pkly',))


def test_hash_matches(excel_compiler):
    assert excel_compiler.hash_matches

    excel_compiler._excel_file_md5_digest = 0
    assert not excel_compiler.hash_matches


def test_pickle_file_rebuilding(excel_compiler):

    input_addrs = ['Sheet1!A11']
    output_addrs = ['Sheet1!D1']

    excel_compiler.trim_graph(input_addrs, output_addrs)
    excel_compiler.to_file()

    pickle_name = excel_compiler.filename + '.pkl'
    yaml_name = excel_compiler.filename + '.yml'

    assert os.path.exists(pickle_name)
    old_hash = excel_compiler._compute_file_md5_digest(pickle_name)

    excel_compiler.to_file()
    assert old_hash == excel_compiler._compute_file_md5_digest(pickle_name)

    os.unlink(yaml_name)
    excel_compiler.to_file()
    new_hash = excel_compiler._compute_file_md5_digest(pickle_name)
    assert old_hash != new_hash

    shutil.copyfile(pickle_name, yaml_name)
    excel_compiler.to_file()
    assert new_hash != excel_compiler._compute_file_md5_digest(pickle_name)


def test_reset(excel_compiler):
    in_address = 'Sheet1!A1'
    out_address = 'Sheet1!D1'

    assert -0.02286 == round(excel_compiler.evaluate(out_address), 5)

    in_value = excel_compiler.cell_map[in_address].value

    excel_compiler._reset(excel_compiler.cell_map[in_address])
    assert excel_compiler.cell_map[out_address].value is None

    excel_compiler._reset(excel_compiler.cell_map[in_address])
    assert excel_compiler.cell_map[out_address].value is None

    excel_compiler.cell_map[in_address].value = in_value
    assert -0.02286 == round(excel_compiler.evaluate(out_address), 5)
    assert -0.02286 == round(excel_compiler.cell_map[out_address].value, 5)


def test_recalculate(excel_compiler):
    out_address = 'Sheet1!D1'

    assert -0.02286 == round(excel_compiler.evaluate(out_address), 5)
    excel_compiler.cell_map[out_address].value = None

    excel_compiler.recalculate()
    assert -0.02286 == round(excel_compiler.cell_map[out_address].value, 5)


def test_evaluate_from_generator(excel_compiler):
    result = excel_compiler.evaluate(
        a for a in ('trim-range!B1', 'trim-range!B2'))
    assert (24, 136) == result


def test_evaluate_empty(excel_compiler):
    assert 0 == excel_compiler.evaluate('Empty!B1')

    excel_compiler.recalculate()
    assert 0 == excel_compiler.evaluate('Empty!B1')

    input_addrs = ['Empty!C1', 'Empty!B2']
    output_addrs = ['Empty!B1', 'Empty!B2']

    excel_compiler.trim_graph(input_addrs, output_addrs)
    excel_compiler._to_text(is_json=True)
    text_excel_compiler = ExcelCompiler._from_text(
        excel_compiler.filename, is_json=True)

    assert [0, None] == text_excel_compiler.evaluate(output_addrs)
    text_excel_compiler.set_value(input_addrs[0], 10)
    assert [10, None] == text_excel_compiler.evaluate(output_addrs)

    text_excel_compiler.set_value(input_addrs[1], 20)
    assert [10, 20] == text_excel_compiler.evaluate(output_addrs)


def test_gen_graph(excel_compiler):
    excel_compiler._gen_graph('B2')

    with pytest.raises(ValueError, match='Unknown seed'):
        excel_compiler._gen_graph(None)

    with pytest.raises(NotImplementedError, match='Linked SheetNames'):
        excel_compiler._gen_graph('=[Filename.xlsx]Sheetname!A1')


def test_value_tree_str(excel_compiler):
    out_address = 'trim-range!B2'
    excel_compiler.evaluate(out_address)

    expected = [
        'trim-range!B2 = 136',
        ' trim-range!B1 = 24',
        '  trim-range!D1:E3 = ((1, 5), (2, 6), (3, 7))',
        '   trim-range!D1 = 1',
        '   trim-range!D2 = 2',
        '   trim-range!D3 = 3',
        '   trim-range!E1 = 5',
        '   trim-range!E2 = 6',
        '   trim-range!E3 = 7',
        ' trim-range!D4:E4 = ((4, 8),)',
        '  trim-range!D4 = 4',
        '  trim-range!E4 = 8',
        ' trim-range!D5 = 100'
    ]
    assert expected == list(excel_compiler.value_tree_str(out_address))


def test_trim_cells(excel_compiler):
    input_addrs = ['trim-range!D5']
    output_addrs = ['trim-range!B2']

    old_value = excel_compiler.evaluate(output_addrs[0])

    excel_compiler.trim_graph(input_addrs, output_addrs)
    excel_compiler._to_text(is_json=True)

    new_value = ExcelCompiler._from_text(
        excel_compiler.filename, is_json=True).evaluate(output_addrs[0])

    assert old_value == new_value


def test_trim_cells_range(excel_compiler):
    input_addrs = [AddressRange('trim-range!D4:E4')]
    output_addrs = ['trim-range!B2']

    old_value = excel_compiler.evaluate(output_addrs[0])

    excel_compiler.trim_graph(input_addrs, output_addrs)

    excel_compiler._to_text()
    excel_compiler = ExcelCompiler._from_text(excel_compiler.filename)
    assert old_value == excel_compiler.evaluate(output_addrs[0])

    excel_compiler.set_value(input_addrs[0], [5, 6], set_as_range=True)
    assert old_value - 1 == excel_compiler.evaluate(output_addrs[0])

    excel_compiler.set_value(input_addrs[0], [4, 6])
    assert old_value - 2 == excel_compiler.evaluate(output_addrs[0])

    excel_compiler.set_value(tuple(next(input_addrs[0].rows)), [5, 6])
    assert old_value - 1 == excel_compiler.evaluate(output_addrs[0])


def test_evaluate_from_non_cells(excel_compiler):
    input_addrs = ['Sheet1!A11']
    output_addrs = ['Sheet1!A11:A13', 'Sheet1!D1', 'Sheet1!B11', ]

    old_values = excel_compiler.evaluate(output_addrs)

    excel_compiler.trim_graph(input_addrs, output_addrs)

    excel_compiler.to_file(file_types='yml')
    excel_compiler = ExcelCompiler.from_file(excel_compiler.filename)
    for expected, result in zip(
            old_values, excel_compiler.evaluate(output_addrs)):
        assert tuple(flatten(expected)) == pytest.approx(tuple(flatten(result)))

    range_cell = excel_compiler.cell_map[output_addrs[0]]
    excel_compiler._reset(range_cell)
    range_value = excel_compiler.evaluate(range_cell.address)
    assert old_values[0] == range_value


def test_validate_calcs(excel_compiler, capsys):
    input_addrs = ['trim-range!D5']
    output_addrs = ['trim-range!B2']

    excel_compiler.trim_graph(input_addrs, output_addrs)
    excel_compiler.cell_map[output_addrs[0]].value = 'JUNK'
    failed_cells = excel_compiler.validate_calcs(output_addrs)

    assert {'mismatch': {
        'trim-range!B2': ('JUNK', 136, '=B1+SUM(D4:E4)+D5')}} == failed_cells

    out, err = capsys.readouterr()
    assert '' == err
    assert 'JUNK' in out


def test_validate_calcs_all_cells(basic_ws):
    formula_cells = basic_ws.formula_cells('Sheet1')
    expected = {
        AddressCell('Sheet1!B2'),
        AddressCell('Sheet1!C2'),
        AddressCell('Sheet1!B3'),
        AddressCell('Sheet1!C3'),
        AddressCell('Sheet1!B4'),
        AddressCell('Sheet1!C4')
    }
    assert expected == set(formula_cells)
    assert {} == basic_ws.validate_calcs()


def test_validate_calcs_excel_compiler(excel_compiler):
    """Find all formula cells w/ values and verify calc"""
    errors = excel_compiler.validate_calcs()
    msg = json.dumps(errors, indent=2)
    assert msg == '{}'

    errors = excel_compiler.validate_calcs('Sheet1!B1')
    msg = json.dumps(errors, indent=2)
    assert msg == '{}'

    # Missing sheets returns empty tuple
    assert len(excel_compiler.formula_cells('JUNK-Sheet!B1')) == 0


def test_evaluate_entire_row_column(excel_compiler):

    value = excel_compiler.evaluate(AddressRange('Sheet1!A:A'))
    expected = excel_compiler.evaluate(AddressRange('Sheet1!A1:A18'))
    assert value == expected
    assert len(value) == 18
    assert not list_like(value[0])

    value = excel_compiler.evaluate(AddressRange('Sheet1!1:1'))
    expected = excel_compiler.evaluate(AddressRange('Sheet1!A1:D1'))
    assert value == expected
    assert len(value) == 4
    assert not list_like(value[0])

    value = excel_compiler.evaluate(AddressRange('Sheet1!A:B'))
    expected = excel_compiler.evaluate(AddressRange('Sheet1!A1:B18'))
    assert value == expected
    assert len(value) == 18
    assert len(value[0]) == 2

    value = excel_compiler.evaluate(AddressRange('Sheet1!1:2'))
    expected = excel_compiler.evaluate(AddressRange('Sheet1!A1:D2'))
    assert value == expected
    assert len(value) == 2
    assert len(value[0]) == 4

    # now from the text based file
    excel_compiler._to_text()
    text_excel_compiler = ExcelCompiler._from_text(excel_compiler.filename)

    value = text_excel_compiler.evaluate(AddressRange('Sheet1!A:A'))
    expected = text_excel_compiler.evaluate(AddressRange('Sheet1!A1:A18'))
    assert value == expected
    assert len(value) == 18
    assert not list_like(value[0])

    value = text_excel_compiler.evaluate(AddressRange('Sheet1!1:1'))
    expected = text_excel_compiler.evaluate(AddressRange('Sheet1!A1:D1'))
    assert value == expected
    assert len(value) == 4
    assert not list_like(value[0])

    value = text_excel_compiler.evaluate(AddressRange('Sheet1!A:B'))
    expected = text_excel_compiler.evaluate(AddressRange('Sheet1!A1:B18'))
    assert len(value) == 18
    assert len(value[0]) == 2
    assert value == expected

    value = text_excel_compiler.evaluate(AddressRange('Sheet1!1:2'))
    expected = text_excel_compiler.evaluate(AddressRange('Sheet1!A1:D2'))
    assert value == expected
    assert len(value) == 2
    assert len(value[0]) == 4


def test_trim_cells_warn_address_not_found(excel_compiler):
    input_addrs = ['trim-range!D5', 'trim-range!H1']
    output_addrs = ['trim-range!B2']

    excel_compiler.evaluate(output_addrs[0])
    excel_compiler.log.warning = mock.Mock()
    excel_compiler.trim_graph(input_addrs, output_addrs)
    assert 1 == excel_compiler.log.warning.call_count


def test_trim_cells_info_buried_input(excel_compiler):
    input_addrs = ['trim-range!B1', 'trim-range!D1']
    output_addrs = ['trim-range!B2']

    excel_compiler.evaluate(output_addrs[0])
    excel_compiler.log.info = mock.Mock()
    excel_compiler.trim_graph(input_addrs, output_addrs)
    assert 2 == excel_compiler.log.info.call_count
    assert 'not a leaf node' in excel_compiler.log.info.mock_calls[1][1][0]


def test_trim_cells_exception_input_unused(excel_compiler):
    input_addrs = ['trim-range!G1']
    output_addrs = ['trim-range!B2']
    excel_compiler.evaluate(output_addrs[0])
    excel_compiler.evaluate(input_addrs[0])

    with pytest.raises(
            ValueError,
            match=' which usually means no outputs are dependant on it'):
        excel_compiler.trim_graph(input_addrs, output_addrs)


def test_compile_error_message_line_number(excel_compiler):
    input_addrs = ['trim-range!D5']
    output_addrs = ['trim-range!B2']

    excel_compiler.trim_graph(input_addrs, output_addrs)

    filename = excel_compiler.filename + '.pickle'
    excel_compiler.to_file(filename)

    excel_compiler = ExcelCompiler.from_file(filename)
    formula = excel_compiler.cell_map[output_addrs[0]].formula
    formula._python_code = '(x)'
    formula.lineno = 3000
    formula.filename = 'a_file'
    with pytest.raises(UnknownFunction, match='File "a_file", line 3000'):
        excel_compiler.evaluate(output_addrs[0])


def test_init_cell_address_error(excel):
    with pytest.raises(ValueError):
        _CellRange(ExcelWrapper.RangeData(
            AddressCell('A1'), '', ((0, ),)))


def test_cell_range_repr(excel):
    cell_range = _CellRange(ExcelWrapper.RangeData(
        AddressRange('sheet!A1:B1'), '', ((0, 0),)))
    assert 'sheet!A1:B1' == repr(cell_range)


def test_cell_repr(excel):
    cell_range = _Cell('sheet!A1', value=0)
    assert 'sheet!A1 -> 0' == repr(cell_range)


def test_gen_gexf(excel_compiler, tmpdir):
    filename = os.path.join(str(tmpdir), 'test.gexf')
    assert not os.path.exists(filename)
    excel_compiler.export_to_gexf(filename)

    # ::TODO: it would good to test this by comparing to an fixture/artifact
    assert os.path.exists(filename)


def test_gen_dot(excel_compiler, tmpdir):
    with pytest.raises(ImportError, match="Package 'pydot' is not installed"):
        excel_compiler.export_to_dot()

    import sys
    mock_imports = (
        'pydot',
    )
    for mock_import in mock_imports:
        sys.modules[mock_import] = mock.MagicMock()

    with mock.patch('networkx.drawing.nx_pydot.write_dot'):
        excel_compiler.export_to_dot()


def test_plot_graph(excel_compiler, tmpdir):
    with pytest.raises(ImportError,
                       match="Package 'matplotlib' is not installed"):
        excel_compiler.plot_graph()

    import sys
    mock_imports = (
        'matplotlib',
        'matplotlib.pyplot',
        'matplotlib.cbook',
        'matplotlib.colors',
        'matplotlib.collections',
        'matplotlib.patches',
    )
    for mock_import in mock_imports:
        sys.modules[mock_import] = mock.MagicMock()
    out_address = 'trim-range!B2'
    excel_compiler.evaluate(out_address)

    with mock.patch('pycel.excelcompiler.nx'):
        excel_compiler.plot_graph()


def test_structured_ref(excel_compiler):
    input_addrs = ['sref!F3']
    output_addrs = ['sref!B3']

    assert 15 == excel_compiler.evaluate(output_addrs[0])
    excel_compiler.trim_graph(input_addrs, output_addrs)

    assert 15 == excel_compiler.evaluate(output_addrs[0])

    excel_compiler.set_value(input_addrs[0], 11)
    assert 20 == excel_compiler.evaluate(output_addrs[0])


@pytest.mark.parametrize(
    'msg, formula', (
        ("Function XYZZY is not implemented. "
         "XYZZY is not a known Excel function", '=xyzzy()'),
        ("Function PLUGH is not implemented. "
         "PLUGH is not a known Excel function\n"
         "Function XYZZY is not implemented. "
         "XYZZY is not a known Excel function", '=xyzzy() + plugh()'),
        ('Function ARABIC is not implemented. '
         'ARABIC is in the "Math and trigonometry" group, '
         'and was introduced in Excel 2013',
         '=ARABIC()'),
    )
)
def test_unknown_functions(fixture_dir, msg, formula):
    excel_compiler = ExcelCompiler.from_file(
        os.path.join(fixture_dir, 'fixture.xlsx.yml'))

    address = AddressCell('s!A1')
    excel_compiler.cell_map[str(address)] = _Cell(
        address, None, formula, excel_compiler.excel
    )
    with pytest.raises(UnknownFunction, match=msg):
        excel_compiler.evaluate(address)

    result = excel_compiler.validate_calcs([address])
    assert 'not-implemented' in result
    assert len(result['not-implemented']) == 1


def test_evaluate_exceptions(fixture_dir):
    excel_compiler = ExcelCompiler.from_file(
        os.path.join(fixture_dir, 'fixture.xlsx.yml'))

    address = AddressCell('s!A1')
    excel_compiler.cell_map[str(address)] = _Cell(
        address, None, '=__REF__("s!A2")', excel_compiler.excel
    )
    address = AddressCell('s!A2')
    excel_compiler.cell_map[str(address)] = _Cell(
        address, None, '=$', excel_compiler.excel
    )

    with pytest.raises(FormulaParserError):
        excel_compiler.evaluate(address)

    result = excel_compiler.validate_calcs(address)
    assert 'exceptions' in result
    assert len(result['exceptions']) == 1


def test_evaluate_empty_intersection(fixture_dir):
    excel_compiler = ExcelCompiler.from_file(
        os.path.join(fixture_dir, 'fixture.xlsx.yml'))

    address = AddressCell('s!A1')
    excel_compiler.cell_map[str(address)] = _Cell(
        address, None, '=_R_(str(_REF_("s!A1:A2") & _REF_("s!B1:B2")))',
        excel_compiler.excel
    )
    assert excel_compiler.evaluate(address) == NULL_ERROR


def test_plugins(excel_compiler):

    input_addrs = ['Sheet1!A11']
    output_addrs = ['Sheet1!D1']
    excel_compiler.trim_graph(input_addrs, output_addrs)
    d1 = -0.022863768173008364

    excel_compiler.recalculate()
    assert pytest.approx(d1) == excel_compiler.evaluate('Sheet1!D1')

    def calc_and_check():
        excel_compiler._eval = None
        excel_compiler.cell_map['Sheet1!D1'].formula.compiled_lambda = None
        excel_compiler.recalculate()
        assert pytest.approx(d1) == excel_compiler.evaluate('Sheet1!D1')

    with mock.patch('pycel.excelformula.ExcelFormula.default_modules', ()):
        with pytest.raises(UnknownFunction):
            calc_and_check()

    with mock.patch('pycel.excelformula.ExcelFormula.default_modules', ()):
        excel_compiler._plugin_modules = ('pycel.excellib', )
        calc_and_check()

    with mock.patch('pycel.excelformula.ExcelFormula.default_modules', ()):
        excel_compiler._plugin_modules = 'pycel.excellib'
        calc_and_check()

    with mock.patch('pycel.excelformula.ExcelFormula.default_modules',
                    ('pycel.excellib', )):
        excel_compiler._plugin_modules = None
        calc_and_check()

    with mock.patch('pycel.excelformula.ExcelFormula.default_modules', ()):
        with pytest.raises(UnknownFunction):
            calc_and_check()


def test_validate_circular_referenced(circular_ws):
    circular_ws.trim_graph(['Sheet1!B3'], ['Sheet1!B2'])

    circular_ws.set_value('Sheet1!B3', 100)
    assert circular_ws.evaluate('Sheet1!B2') == pytest.approx(16.66666667)

    circular_ws.set_value('Sheet1!B3', 200)
    assert circular_ws.evaluate('Sheet1!B2') == pytest.approx(33.33333333)

    circular_ws.set_value('Sheet1!B3', 500)
    assert circular_ws.evaluate('Sheet1!B2') == pytest.approx(83.33333333)

    circular_ws.set_value('Sheet1!A2', 0.1234)
    assert circular_ws.evaluate('Sheet1!B2') == pytest.approx(54.92255652)
