"""Numpydoc fixtures: a section that documents None means "nothing here".

Both functions must produce no findings. `Parameters / ---------- / None` used to
be parsed as a parameter literally named None, and `Returns / ------- / None`
was read as a documented return value because the underline sat between the
header and the value.
"""


def numpy_none_params():
    """Do it.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """


def numpy_none_return_only():
    """Do it.

    Returns
    -------
    None
    """
