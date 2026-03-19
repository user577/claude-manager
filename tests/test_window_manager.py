from src.core.window_manager import Rect, compute_layout


def test_grid_2x2_four():
    work = Rect(0, 0, 1920, 1080)
    pos = compute_layout(work, "grid_2x2", 4)
    assert len(pos) == 4
    assert pos[0] == Rect(0, 0, 960, 540)
    assert pos[1] == Rect(960, 0, 960, 540)
    assert pos[2] == Rect(0, 540, 960, 540)
    assert pos[3] == Rect(960, 540, 960, 540)


def test_grid_2x2_two():
    work = Rect(0, 0, 1920, 1080)
    pos = compute_layout(work, "grid_2x2", 2)
    assert len(pos) == 2
    # 2 items: 1 row, 2 cols
    assert pos[0] == Rect(0, 0, 960, 1080)
    assert pos[1] == Rect(960, 0, 960, 1080)


def test_grid_2x2_one():
    work = Rect(0, 0, 1920, 1080)
    pos = compute_layout(work, "grid_2x2", 1)
    assert len(pos) == 1
    assert pos[0] == Rect(0, 0, 1920, 1080)


def test_vertical_three():
    work = Rect(0, 0, 1920, 1080)
    pos = compute_layout(work, "vertical", 3)
    assert len(pos) == 3
    assert pos[0] == Rect(0, 0, 1920, 360)
    assert pos[1] == Rect(0, 360, 1920, 360)
    assert pos[2] == Rect(0, 720, 1920, 360)


def test_horizontal_two():
    work = Rect(0, 0, 3440, 1440)
    pos = compute_layout(work, "horizontal", 2)
    assert len(pos) == 2
    assert pos[0] == Rect(0, 0, 1720, 1440)
    assert pos[1] == Rect(1720, 0, 1720, 1440)


def test_single_four():
    work = Rect(0, 0, 1920, 1080)
    pos = compute_layout(work, "single", 4)
    assert len(pos) == 4
    for p in pos:
        assert p == Rect(0, 0, 1920, 1080)


def test_offset_work_area():
    # Taskbar offset
    work = Rect(0, 40, 1920, 1040)
    pos = compute_layout(work, "grid_2x2", 4)
    assert pos[0] == Rect(0, 40, 960, 520)
    assert pos[1] == Rect(960, 40, 960, 520)
    assert pos[2] == Rect(0, 560, 960, 520)
    assert pos[3] == Rect(960, 560, 960, 520)


def test_ultrawide_grid():
    work = Rect(0, 0, 3440, 1440)
    pos = compute_layout(work, "grid_2x2", 4)
    assert pos[0] == Rect(0, 0, 1720, 720)
    assert pos[3] == Rect(1720, 720, 1720, 720)
