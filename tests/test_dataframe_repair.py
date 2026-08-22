"""`repair_shifted_multilevel_header` trên các bảng thật đã kiểm bằng tay.

Mọi CSV dưới đây là bản sao nguyên văn vài dòng đầu của một bảng có thật trong
`data/tables`, ghi rõ id trong docstring. Xem `docs/multiyear_failures_2026-08-22.md` §5
cho vì sao lớp lỗi này đắt: cột mang số thật thì tên là `Unnamed:`, còn cột có tên lại
mang số của kỳ khác, nên câu trả lời sai vẫn trông hợp lý.
"""

from __future__ import annotations

import io

import pandas as pd

from finance_qa.modules.tools.dataframe import repair_shifted_multilevel_header


def frame(csv: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(csv.lstrip("\n")), dtype=str, keep_default_na=False)


def test_hai_nhom_bang_nhau_khong_bi_gop_thanh_mot():
    """KLB_financial_statements_2019_consolidated|67.

    Bản cũ dán cả bốn leaf vào `Số cuối năm` nên hai cột đầu năm mang tên cuối năm, và
    tên cột trùng nhau. Cột `Số đầu năm` khi đó trả về giá trị hợp lý *cuối* kỳ.
    """
    df = repair_shifted_multilevel_header(
        frame(
            """
,Số cuối năm,Số đầu năm,,
Giá trị ghi số,Giá trị hợp lý,Giá trị ghi số,Giá trị hợp lý,
"Tiền mặt, vàng bạc, đá quý",694.761,694.761,519.751,519.751
Tiền gửi tại Ngân hàng Nhà nước,2.998.548,2.998.548,1.852.903,1.852.903
"""
        )
    )
    assert list(df.columns) == [
        "Unnamed: 0",
        "Số cuối năm | Giá trị ghi số",
        "Số cuối năm | Giá trị hợp lý",
        "Số đầu năm | Giá trị ghi số",
        "Số đầu năm | Giá trị hợp lý",
    ]
    assert df.iloc[0]["Số đầu năm | Giá trị hợp lý"] == "519.751"
    assert len(df) == 2


def test_ba_nhom_rong_khac_nhau():
    """SJG_financial_statements_2018_consolidated|45, hai bảng của câu 866.

    Nhóm giữa rộng 3 leaf còn hai nhóm ngoài rộng 2, nên chia đều là sai. Biên nhóm suy
    từ chỗ leaf đầu (`Phải nộp`) lặp lại.
    """
    df = repair_shifted_multilevel_header(
        frame(
            """
,Tại ngày 06/4/2018,Số phát sinh trong năm,Tại ngày 31/12/2018,,,,
Phải nộp,Phải thu,Phải nộp,Đã nộp,Giảm khác,Phải nộp,Phải thu,
Thuế và các khoản phải nộp Nhà nước,337.129.394.454,7.408.733.781,561.976.079.979,(607.842.829.321),(920.916.101),290.178.963.228,7.245.967.998
"""
        )
    )
    assert list(df.columns) == [
        "Unnamed: 0",
        "Tại ngày 06/4/2018 | Phải nộp",
        "Tại ngày 06/4/2018 | Phải thu",
        "Số phát sinh trong năm | Phải nộp",
        "Số phát sinh trong năm | Đã nộp",
        "Số phát sinh trong năm | Giảm khác",
        "Tại ngày 31/12/2018 | Phải nộp",
        "Tại ngày 31/12/2018 | Phải thu",
    ]
    # Con số 561.976.079.979 là phát sinh trong năm, không phải số dư cuối kỳ. Đọc theo
    # tên cột trước khi sửa thì nó chính là "Tại ngày 31/12/2018", và câu 866 trả sai năm.
    assert df.iloc[0]["Số phát sinh trong năm | Phải nộp"] == "561.976.079.979"


def test_bo_qua_dong_tieu_de_muc():
    """DTK_financial_statements_2019_consolidated|29: dòng 0 là nhãn mục `Phải nộp`.

    Một leaf duy nhất nên không phải header dòng hai.
    """
    csv = """
,01/01/2019(VND),Số phải nộptrong năm,Số đã thực nộptrong năm,31/12/2019(VND)
Phải nộp,,,,
Thuế giá trị gia tăng,57.162.354.530,395.279.236.406,430.475.197.672,21.966.393.264
"""
    assert repair_shifted_multilevel_header(frame(csv)).equals(frame(csv))


def test_bo_qua_khi_con_cot_ngoai_pham_vi_leaf_co_du_lieu():
    """DIG_financial_statements_2020_consolidated|30: bảng lệch không đều theo dòng.

    Bốn leaf phủ cột 2..5, nhưng cột 6 vẫn có `Tổng cộng` và số ở các dòng dưới, nên
    không thể tin cách chia nào. Bản cũ vẫn sửa và cho ra tên trùng nhau.
    """
    csv = """
,Lĩnh vực kinh doanh,Số cuối năm,Số đầu năm,,,
Giá trị,%,Giá trị,%,,,
"Công ty Cổ phần DIC Số 4",Xây lắp,128.979.496.061,"40,01%",132.700.596.296,"39,29%",
Tổng cộng,,,,,,360.249.748.500
"""
    assert repair_shifted_multilevel_header(frame(csv)).equals(frame(csv))


def test_bo_qua_khi_so_nhom_khong_khop_so_lan_lap():
    """Hai nhãn nhóm nhưng leaf đầu chỉ xuất hiện một lần: không suy được biên."""
    csv = """
,Số cuối năm,Số đầu năm,,,
Giá trị ghi số,Giá trị hợp lý,Nguyên giá,Khấu hao,,
Tiền mặt,694.761,694.761,519.751,519.751,
"""
    assert repair_shifted_multilevel_header(frame(csv)).equals(frame(csv))


def test_bo_qua_dong_du_lieu_co_so():
    """Dòng 0 có số thì đó là dữ liệu, không phải header."""
    csv = """
,Số cuối năm,Số đầu năm,,
Giá trị ghi số,694.761,Giá trị ghi số,519.751,
Tiền mặt,694.761,694.761,519.751,519.751
"""
    assert repair_shifted_multilevel_header(frame(csv)).equals(frame(csv))
