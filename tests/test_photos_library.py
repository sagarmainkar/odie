"""Which files stand for a picture (odie.photos.library.pick_copies): the thumbnail is Photos' smallest copy; the big
one is Photos' large JPEG copy, never a movie file (a video's original is a .mov, which no image reader opens)."""
from odie.photos.library import pick_copies


def test_the_big_copy_is_photos_large_jpeg_not_the_original(tmp_path):
    small = tmp_path / "x_4_5005_c.jpeg"
    large = tmp_path / "x_1_102_o.jpeg"
    small.write_bytes(b"1" * 10)
    large.write_bytes(b"1" * 100)
    original = tmp_path / "IMG_1.HEIC"
    original.write_bytes(b"1" * 1000)
    assert pick_copies([str(small), str(large)], str(original)) == (str(small), str(large))  # the 2048 px JPEG, which anything can open
    assert pick_copies([str(small)], str(original)) == (str(small), str(original))  # no large copy: the original, a still image
    movie = tmp_path / "clip.mov"
    movie.write_bytes(b"1" * 5000)
    assert pick_copies([str(small)], str(movie)) == (str(small), str(small))  # a movie is never the big copy
    assert pick_copies([], str(movie)) == (None, None)
    assert pick_copies([], None) == (None, None)
