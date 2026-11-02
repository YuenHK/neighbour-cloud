from tools.clean_litter_dataset import clean


def test_clean_quarantines_entire_leaked_source_but_preserves_test():
    items = [{'source_identity': source, 'label': label, 'split': split}
             for source, label, split in [('a', 'plastic_bottle', 'train'),
                                          ('a', 'paper_cup', 'train'),
                                          ('b', 'plastic_bottle', 'test')]]
    result = clean({'items': items, 'limitations': []}, ['same', 'other', 'same'])
    assert result['items'] == [items[-1]]
    assert result['deduplication']['removed_crops'] == 2
    assert result['deduplication']['remaining_cross_split_hash_groups'] == 0


def test_conflicting_labels_are_quarantined_even_in_same_split():
    items = [{'source_identity': source, 'label': label, 'split': 'train'}
             for source, label in [('a', 'paper_cup'), ('b', 'plastic_bottle')]]
    result = clean({'items': items, 'limitations': []}, ['same', 'same'])
    assert not result['items']
    assert result['deduplication']['conflicting_label_hash_groups'] == 1


def test_source_scene_groups_all_crops_from_the_same_bower_photo():
    items = [{'source_identity': path, 'source_group': 'bower', 'scene': photo,
              'label': 'paper_ball_package', 'split': split}
             for path, photo, split in [('one', 'photo-a', 'train'),
                                        ('two', 'photo-a', 'train'),
                                        ('three', 'photo-b', 'test')]]
    result = clean({'items': items, 'limitations': []}, ['same', 'other', 'same'])
    assert len(result['items']) == 1
    assert result['items'][0]['split'] == 'test'
