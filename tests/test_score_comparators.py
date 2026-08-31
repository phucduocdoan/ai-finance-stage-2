"""Hai bộ chấm phải khớp tuyệt đối trên nhãn năm.

Dung sai 1% tương đối cho 2018 lệch 2019 đúng 0.05%, nên mọi câu "năm nào" đều lọt.
Lỗi này chỉ hiện ra khi pipeline bắt đầu trả về năm thật (`project_year`), nên nó phải
được chặn trước khi đo bất cứ thay đổi nào ở lớp câu đó.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "dev"))

from score_clean_eval import correct  # noqa: E402

# `scripts/score_gold75.py` is gitignored as unreviewed WIP, so a clean clone does not
# have it. The rule below has to hold in both bộ chấm, hence the skip rather than a
# second copy of the assertions.
close = getattr(pytest.importorskip("score_gold75"), "close")

TOL = 0.01


def test_nam_lech_mot_bi_cham_sai():
    assert not correct(2019, 2018)
    assert not close(2019.0, 2018.0, TOL)


def test_nam_dung_thi_dung():
    assert correct(2018, 2018)
    assert correct("2018", 2018)
    assert close(2018.0, 2018.0, TOL)


def test_tra_so_tien_cho_cau_hoi_nam_thi_sai():
    assert not correct(703992790108.0, 2018)
    assert not close(703992790108.0, 2018.0, TOL)


def test_so_tien_van_dung_dung_sai_tuong_doi():
    assert correct(1045.55, 1045.6)
    assert close(1045.55, 1045.6, TOL)
    assert not correct(1045.55, 1100.0)
    assert not close(1045.55, 1100.0, TOL)


def test_so_tien_tinh_co_roi_vao_khoang_nam_thi_van_doi_khop_dung():
    """Đánh đổi đã biết: nhãn 2050.0 là số tiền sẽ bị đòi khớp tuyệt đối.

    Không có nhãn nào như vậy trong cả hai tập (kiểm 2026-08-22: 3 nhãn năm ở clean eval,
    3 ở gold75, đều là câu "năm nào"), nên đánh đổi này chưa tốn câu nào.
    """
    assert not correct(2050.4, 2050)
    assert not close(2050.4, 2050.0, TOL)
