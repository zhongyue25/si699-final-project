import matplotlib as mpl
import matplotlib.pyplot as plt

import config

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e4e3df"

MEMBER = "#2a78d6"
CASUAL = "#eb6834"
INSIDE = "#1baf7a"
OUTSIDE = "#4a3aa7"
NEUTRAL = "#8a8983"

RIDER_COLORS = {"member": MEMBER, "casual": CASUAL}


def apply():
    mpl.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.labelcolor": TEXT_MUTED,
            "axes.edgecolor": GRID,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "xtick.color": TEXT_MUTED,
            "ytick.color": TEXT_MUTED,
            "text.color": TEXT,
            "lines.linewidth": 2,
            "legend.frameon": False,
        }
    )


def save(fig, name):
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(config.FIGURES_DIR / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
