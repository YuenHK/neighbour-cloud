from tools.prepare_bower_dataset import mapped_label


def test_maps_target_bower_categories():
    assert mapped_label("Plastic - Hard", "Bottle") == "plastic_bottle"
    assert mapped_label("Metal", "Can/Tin/Cylinder") == "aluminium_can"
    assert mapped_label("Fiber - Paper", "Cup/Tub/Bowl/Bucket") == "paper_cup"
    assert (
        mapped_label("Plastic - Soft", "Flexibles/Bag/Wrapper/Foil/Net")
        == "paper_ball_package"
    )


def test_rejects_material_and_object_mismatches():
    assert mapped_label("Glass - Non-coloured", "Bottle") is None
    assert mapped_label("Hard plastic", "Cup/Tub/Bowl/Bucket") is None
    assert mapped_label("Metal", "Wrapper/Foil/Net/Bag/Flexibles") is None
