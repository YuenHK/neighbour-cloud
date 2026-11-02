import csv

from tools.audit_person_provenance import audit_provenance, photo_identity


def test_flickr_identity_is_stable_across_owner_and_size_urls():
    assert photo_identity({'OriginalLandingURL': 'https://www.flickr.com/photos/owner/12345/'}) == 'flickr:12345'
    assert photo_identity({'OriginalURL': 'https://farm.staticflickr.com/42/12345_secret_z.jpg'}) == 'flickr:12345'


def test_shared_photographer_is_flagged_without_calling_photos_duplicates(tmp_path):
    path = tmp_path / 'metadata.csv'
    fields = ['ImageID', 'OriginalLandingURL', 'OriginalURL', 'AuthorProfileURL', 'Author', 'Title', 'License']
    with path.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for image, photo in [('reg', '123'), ('val', '456')]:
            writer.writerow({'ImageID': image, 'OriginalLandingURL': f'https://flickr.com/photos/owner/{photo}',
                             'AuthorProfileURL': 'https://flickr.com/people/owner/',
                             'Author': 'Public Author', 'License': 'https://creativecommons.org/licenses/by/2.0/'})
    result = audit_provenance(path, {'reg'}, {'val'})
    assert result['same_photo_groups'] == []
    assert len(result['shared_author_groups']) == 1
    assert result['quarantined_validation_ids'] == ['val']
    assert result['validation_eligible_ids'] == []
    assert result['redistribution_approved'] is False


def test_missing_metadata_cannot_be_treated_as_an_independent_source(tmp_path):
    path = tmp_path / 'metadata.csv'
    path.write_text('ImageID,OriginalLandingURL,AuthorProfileURL,Author,License\n')
    result = audit_provenance(path, {'reg'}, {'val'})
    assert result['missing_metadata_ids'] == ['reg', 'val']
    assert result['validation_eligible_ids'] == []
