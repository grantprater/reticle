import os
import sys

# `reticle retire` runs its numeric work on one thread; the limits must be set
# before numpy loads, which importing the cli does.
if "retire" in sys.argv[1:]:
    for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(_k, "1")

from .cli import main  # noqa: E402

raise SystemExit(main())
