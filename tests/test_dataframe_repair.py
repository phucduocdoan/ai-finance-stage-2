"""`repair_shifted_multilevel_header` trên các bảng thật đã kiểm bằng tay.

Mọi CSV dưới đây là bản sao nguyên văn vài dòng đầu của một bảng có thật trong
`data/tables`, ghi rõ id trong docstring. Xem `docs/investigations/multiyear_failures_2026-08-22.md` §5
cho vì sao lớp lỗi này đắt: cột mang số thật thì tên là `Unnamed:`, còn cột có tên lại
mang số của kỳ khác, nên câu trả lời sai vẫn trông hợp lý.
"""

from __future__ import annotations

import io

import pandas as pd

from finance_qa.modules.tools.dataframe import (
    repair_group_leaf_header,
    repair_right_shifted_columns,
    repair_shifted_multilevel_header,
)


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


def test_chi_nhom_cuoi_co_leaf():
    """ACB_financial_statements_2018_consolidated|2.

    Ba cột đầu là cột đơn, chỉ `Tại ngày` trải hai kỳ, nên leaf đầu không lặp lại và
    `repair_shifted_multilevel_header` bỏ qua. Kỳ 2017 khi đó tên là `Unnamed:`, và hỏi
    `Tại ngày` trả về 2018 mà không báo lỗi gì.
    """
    df = repair_group_leaf_header(
        frame(
            """
STT,Chỉ tiêu,Thuyết minh,Tại ngày,
31.12.2018Triệu VND,31.12.2017Triệu VND,,,
A,TÀI SẢN,,,
I,"Tiền mặt, vàng bạc, đá quý",4,6.129.169,4.851.710
"""
        )
    )
    assert list(df.columns) == [
        "STT",
        "Chỉ tiêu",
        "Thuyết minh",
        "Tại ngày | 31.12.2018Triệu VND",
        "Tại ngày | 31.12.2017Triệu VND",
    ]
    assert df.iloc[1]["Tại ngày | 31.12.2017Triệu VND"] == "4.851.710"
    assert len(df) == 2


def test_bo_qua_khi_moi_cot_du_lieu_da_co_ten():
    """Không cột nào mang dữ liệu mà thiếu tên thì không có gì phải sửa."""
    csv = """
STT,Chỉ tiêu,Số cuối năm,Số đầu năm
Ghi chú,,,
I,Tiền mặt,694.761,519.751
"""
    assert repair_group_leaf_header(frame(csv)).equals(frame(csv))


def test_dich_ten_cot_sang_phai_khi_header_thieu_o_goc():
    """DTK_financial_statements_2024_consolidated|9, câu 214.

    Header có 5 tên và một ô rỗng cuối, dữ liệu có 6 giá trị, giá trị đầu là số thứ tự
    không có tên. `Số năm nay` vì thế mang mã thuyết minh `VI.1` và câu 214 chết với
    `could not convert string to float: 'VI.1'`.
    """
    df = repair_right_shifted_columns(
        frame(
            """
CHỈ TIÊU,Mã số,Thuyết minh,Số năm nay,Số năm trước,
1.,Doanh thu bán hàng và cung cấp dịch vụ,01,VI.1,12.839.301.284.671,11.830.033.488.478
2.,Các khoản giảm trừ doanh thu,02,,-,-
"""
        )
    )
    assert list(df.columns) == [
        "STT",
        "CHỈ TIÊU",
        "Mã số",
        "Thuyết minh",
        "Số năm nay",
        "Số năm trước",
    ]
    assert df.iloc[0]["Số năm nay"] == "12.839.301.284.671"


def test_bo_qua_khi_cot_nhan_dung_cho():
    """Cột `Chỉ tiêu` đang mang chữ thật thì bảng không lệch, dù cột cuối vô danh."""
    csv = """
Chỉ tiêu,Mã số,Số năm nay,Số năm trước,
Doanh thu bán hàng và cung cấp dịch vụ,01,12.839.301.284.671,11.830.033.488.478,
Giá vốn hàng bán và dịch vụ đã cung cấp,11,11.611.330.946.505,10.592.634.223.554,
"""
    assert repair_right_shifted_columns(frame(csv)).equals(frame(csv))
