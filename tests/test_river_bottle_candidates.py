import pytest

from tools.prepare_river_bottles import parse_annotation, select_candidates


def entries():
    return [{'path': path, 'type': 'blob', 'mode': '100644', 'sha': 'a' * 40, 'size': 100}
            for path in ('001-river/a.jpg', '001-river/a.xml', '001-river/b.jpg', '001-river/b.xml',
                         '002-river/c.jpg', '002-river/c.xml')]


def test_selects_one_pair_per_session_without_assigning_training_split():
    found = select_candidates({'truncated': False, 'tree': entries()})
    assert [item['path'] for item in found] == ['001-river/a.xml', '002-river/c.xml']
    assert [item['source_group'] for item in found] == ['001-river', '002-river']
    assert all(item['split'] is None for item in found)


def test_truncated_tree_and_unsafe_paths_are_not_silently_accepted():
    with pytest.raises(ValueError):
        select_candidates({'truncated': True, 'tree': entries()})
    assert select_candidates({'truncated': False, 'tree': entries() + [
        {'path': '../a.xml', 'type': 'blob', 'mode': '100644', 'sha': 'b' * 40, 'size': 1}]}) == select_candidates(
            {'truncated': False, 'tree': entries()})


def xml(name='Plastic Bottle', box='1 2 9 8'):
    x1, y1, x2, y2 = box.split()
    return f'''<annotation><folder>001-river</folder><filename>a.jpg</filename>
      <size><width>10</width><height>10</height></size><object><name>{name}</name>
      <difficult>1</difficult><truncated>1</truncated><bndbox><xmin>{x1}</xmin><ymin>{y1}</ymin>
      <xmax>{x2}</xmax><ymax>{y2}</ymax></bndbox></object></annotation>'''.encode()


def test_preserves_raw_voc_coordinates_and_difficult_flags():
    item = parse_annotation(xml(), '001-river/a.xml')
    assert item['objects'][0]['bbox_voc_raw'] == [1, 2, 9, 8]
    assert item['objects'][0]['difficult'] == 1 and item['objects'][0]['truncated'] == 1
    assert item['coordinate_convention_verified'] is False


@pytest.mark.parametrize('payload', [xml('Metal'), xml(box='9 2 1 8'), b'<!DOCTYPE x><annotation/>',
                                     '<!DOCTYPE x><annotation/>'.encode('utf-16')])
def test_invalid_or_ambiguous_annotation_is_rejected(payload):
    with pytest.raises(ValueError):
        parse_annotation(payload, '001-river/a.xml')
