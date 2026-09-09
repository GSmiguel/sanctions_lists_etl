from openpyxl import load_workbook

from sanctions_lists_etl.excel import write_workbook
from sanctions_lists_etl.parser import COLUMNS, parse_sdn_advanced, rows_from_records


def test_write_workbook_roundtrip(sample_xml, tmp_path):
    rows = rows_from_records(parse_sdn_advanced(sample_xml))
    dest = write_workbook(rows, tmp_path / "out.xlsx", metadata={"source": "test"})

    workbook = load_workbook(dest)
    sheet = workbook["SDN"]
    header = [cell.value for cell in sheet[1]]
    assert header == [name for _, name in COLUMNS]
    assert sheet.max_row == len(rows) + 1
    assert sheet.freeze_panes == "A2"
    assert "info" in workbook.sheetnames


def test_long_values_are_clipped(tmp_path):
    rows = [{name: ("x" * 40_000 if name == "enderecos" else "") for _, name in COLUMNS}]
    dest = write_workbook(rows, tmp_path / "big.xlsx")
    sheet = load_workbook(dest)["SDN"]
    assert len(sheet.cell(row=2, column=[n for _, n in COLUMNS].index("enderecos") + 1).value) <= 32_000
