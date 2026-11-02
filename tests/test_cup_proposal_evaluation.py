from edge_hub.object_proposals import GenericProposal
from tools.evaluate_cup_proposals import matched_boxes


def test_one_proposal_cannot_count_two_overlapping_truths_as_two_hits():
    truths = [[0, 0, 10, 10], [0, 0, 10, 10]]
    proposals = [GenericProposal('coco:cup', .9, (0, 0, 10, 10))]
    assert matched_boxes(truths, proposals) == 1


def test_bottle_cannot_satisfy_cup_truth_or_lower_iou_requirement():
    assert matched_boxes([[0, 0, 10, 10]], [GenericProposal('coco:bottle', .9, (0, 0, 10, 10))]) == 0
    assert matched_boxes([[0, 0, 10, 10]], [GenericProposal('coco:cup', .9, (0, 0, 3, 3))]) == 0
