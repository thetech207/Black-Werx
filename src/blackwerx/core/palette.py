"""Thread palette: DMC color chart + custom colors.

Color specs used throughout the app:
  "#rrggbb"      custom color
  "dmc:NNN"      DMC floss number (resolved to its standard hex)

The built-in table is a curated starter set of common DMC cotton floss
colors; it can be extended by editing DMC_COLORS.
"""

from __future__ import annotations

# (code, name, hex) — common DMC cotton floss colors.
# Hex values are approximate published conversions.
DMC_COLORS: list[tuple[str, str, str]] = [
    ("310", "Black", "#000000"),
    ("317", "Pewter Gray", "#4C4C4C"),
    ("318", "Steel Gray Lt", "#8A8A8A"),
    ("319", "Pewter Gray Vy Dk", "#2B2B2B"),
    ("321", "Red", "#C8102E"),
    ("347", "Salmon", "#F4A460"),
    ("350", "Coral", "#FF6F61"),
    ("380", "Melon Vy Lgt", "#FFCBA4"),
    ("383", "Terra Cotta Lt", "#D98880"),
    ("385", "Terra Cotta Vy Lgt", "#E8A090"),
    ("386", "Terra Cotta Med", "#C08070"),
    ("402", "Hazel Brown Vy Lgt", "#C8A878"),
    ("433", "Brown Med", "#8B5A2B"),
    ("434", "Brown Vy Lgt", "#A67C52"),
    ("435", "Brown Vy Dk", "#6B4423"),
    ("436", "Tan", "#D2B48C"),
    ("437", "Tan Vy Lt", "#E8D5B0"),
    ("438", "Tan Lgt", "#D8C49A"),
    ("444", "Lemon Yellow Vy Lgt", "#FFFACD"),
    ("445", "Lemon Lgt", "#FFFFE0"),
    ("501", "Blue Green Vy Dk", "#004040"),
    ("502", "Blue Green Vy Dk", "#005050"),
    ("503", "Blue Green Dk", "#0F4C4C"),
    ("504", "Blue Green Med", "#2E8B8B"),
    ("517", "Wedgewood Lgt", "#A8D8EA"),
    ("518", "Wedgewood Vy Lgt", "#C8E8F8"),
    ("519", "Sky Blue Vy Dk", "#4682B4"),
    ("520", "Sky Blue Dk", "#5B9BD5"),
    ("522", "Sky Blue Vy Lgt", "#87CEEB"),
    ("523", "Sky Blue Lgt", "#A0D8EF"),
    ("550", "Violet Vy Lgt", "#E6E6FA"),
    ("552", "Violet Lgt", "#D8BFD8"),
    ("553", "Violet", "#B57EDC"),
    ("554", "Violet Lgt", "#DDA0DD"),
    ("561", "Orange Vy Lgt", "#FFE4B5"),
    ("562", "Orange Lgt", "#FFDAB9"),
    ("600", "Cranberry Vy Lgt", "#F5C6C6"),
    ("601", "Cranberry Lgt", "#F09090"),
    ("602", "Cranberry Vy Dk", "#8B0000"),
    ("603", "Cranberry Dk", "#A52A2A"),
    ("604", "Cranberry Med", "#C04040"),
    ("605", "Cranberry Vy Lgt", "#E8A0A0"),
    ("606", "Orange-Red Vy Lgt", "#FFB6C1"),
    ("612", "Drab Brown Lgt", "#C4A77D"),
    ("640", "Beige Gray Vy Dk", "#8B7D6B"),
    ("642", "Beige Gray Dk", "#A3907C"),
    ("644", "Beige Gray Vy Lgt", "#C4B09F"),
    ("647", "Beige Gray Lgt", "#D4C4B0"),
    ("648", "Beige Gray Vy Lgt", "#E0D0BC"),
    ("676", "Old Gold Lgt", "#DAA520"),
    ("677", "Old Gold Vy Lgt", "#E6BE8A"),
    ("699", "Green Vy Dk", "#1B5E20"),
    ("700", "Green Vy Dk", "#2E7D32"),
    ("701", "Green Med", "#4CAF50"),
    ("702", "Kelly Green", "#43A047"),
    ("703", "Chartreuse Vy Dk", "#33691E"),
    ("704", "Chartreuse Dk", "#558B2F"),
    ("705", "Chartreuse Med", "#7CB342"),
    ("712", "Chartreuse Vy Lgt", "#C5E1A5"),
    ("738", "Tan Vy Lgt", "#F0E68C"),
    ("739", "Tan Lgt", "#F5DEB3"),
    ("740", "Tangerine Vy Lgt", "#FFB347"),
    ("741", "Tangerine Lgt", "#FFCC80"),
    ("742", "Tangerine Med", "#FF9933"),
    ("743", "Tangerine Vy Dk", "#CC6600"),
    ("744", "Yellow Pale", "#FFFF99"),
    ("745", "Yellow Lgt", "#FFFFCC"),
    ("746", "Off White", "#FFFFF0"),
    ("762", "Pearl Gray Vy Lgt", "#F5F5F5"),
    ("783", "Topaz Vy Lgt", "#F0E68C"),
    ("798", "Delft Blue Lgt", "#B0C4DE"),
    ("799", "Delft Blue Vy Lgt", "#ADD8E6"),
    ("800", "Pale Blue Vy Dk", "#4682B4"),
    ("801", "Pale Blue Dk", "#5B9BD5"),
    ("802", "Pale Blue Med", "#87CEEB"),
    ("803", "Pale Blue Vy Lgt", "#B0E0E6"),
    ("804", "Pale Blue Lgt", "#ADD8E6"),
    ("807", "Aqua Vy Dk", "#008B8B"),
    ("813", "Blue Vy Lgt", "#87CEFA"),
    ("814", "Blue Lgt", "#ADD8E6"),
    ("815", "Blue Med", "#4682B4"),
    ("816", "Blue Vy Dk", "#1E3A8A"),
    ("817", "Royal Blue Dk", "#000080"),
    ("819", "Baby Blue Vy Lgt", "#E0F0FF"),
    ("820", "Royal Blue Lgt", "#4169E1"),
    ("822", "Navy Blue Vy Dk", "#000033"),
    ("823", "Navy Blue Dk", "#000066"),
    ("824", "Blue Vy Dk", "#191970"),
    ("825", "Blue Dk", "#0000CD"),
    ("826", "Blue Med", "#0000FF"),
    ("827", "Blue Vy Lgt", "#6666FF"),
    ("828", "Blue Lgt", "#9999FF"),
    ("829", "Blue Vy Lgt", "#CCCCFF"),
    ("830", "Golden Yellow Dk", "#DAA520"),
    ("831", "Golden Yellow Med", "#FFD700"),
    ("832", "Golden Yellow Vy Lgt", "#FFFACD"),
    ("833", "Golden Yellow Lgt", "#FFECB3"),
    ("834", "Golden Yellow Vy Lgt", "#FFF8DC"),
    ("838", "Beige Brown Vy Dk", "#8B7355"),
    ("839", "Beige Brown Dk", "#A08060"),
    ("840", "Beige Brown Med", "#BC8F8F"),
    ("841", "Beige Brown Vy Lgt", "#D2B48C"),
    ("842", "Beige Brown Lgt", "#E6C8A0"),
    ("843", "Beige Brown Vy Lgt", "#F0E0C0"),
    ("844", "Beige Brown Vy Lgt", "#F5E6D3"),
    ("845", "Beige Brown Vy Lgt", "#FAF0E6"),
    ("869", "Hazel Brown Vy Dk", "#654321"),
    ("890", "Pistachio Green Vy Dk", "#556B2F"),
    ("891", "Pistachio Green Dk", "#8FBC8F"),
    ("892", "Pistachio Green Med", "#90EE90"),
    ("893", "Pistachio Green Vy Lgt", "#98FB98"),
    ("894", "Pistachio Green Lgt", "#B0E0B0"),
    ("895", "Pistachio Green Vy Lgt", "#C0E8C0"),
    ("904", "Parrot Green Vy Dk", "#006400"),
    ("905", "Parrot Green Dk", "#228B22"),
    ("906", "Parrot Green Med", "#32CD32"),
    ("907", "Parrot Green Vy Lgt", "#90EE90"),
    ("909", "Parrot Green Lgt", "#98FB98"),
    ("910", "Emerald Green Vy Dk", "#004D00"),
    ("911", "Emerald Green Dk", "#006400"),
    ("912", "Emerald Green Med", "#228B22"),
    ("913", "Emerald Green Vy Lgt", "#32CD32"),
    ("915", "Emerald Green Lgt", "#90EE90"),
    ("916", "Emerald Green Vy Lgt", "#98FB98"),
    ("917", "Emerald Green Vy Lgt", "#B0E0B0"),
    ("918", "Red Vy Lgt", "#FFB6C1"),
    ("919", "Red Lgt", "#FFC0CB"),
    ("920", "Copper Vy Lgt", "#E6B8A2"),
    ("921", "Copper Lgt", "#F0C8A0"),
    ("922", "Copper Med", "#D2691E"),
    ("923", "Copper Vy Dk", "#8B4513"),
    ("924", "Copper Dk", "#A0522D"),
    ("925", "Copper Vy Lgt", "#DEB887"),
    ("926", "Copper Vy Lgt", "#E8C8A0"),
    ("927", "Copper Vy Lgt", "#F0D0B0"),
    ("928", "Copper Vy Lgt", "#F5DEB3"),
    ("939", "Navy Vy Dk", "#000033"),
    ("940", "Navy Dk", "#000066"),
    ("941", "Navy Med", "#0000CD"),
    ("943", "Navy Vy Lgt", "#333399"),
    ("945", "Navy Lgt", "#6666CC"),
    ("947", "Navy Vy Lgt", "#9999FF"),
    ("951", "Aqua Vy Dk", "#008B8B"),
    ("952", "Aqua Dk", "#20B2AA"),
    ("953", "Aqua Med", "#48D1CC"),
    ("954", "Aqua Vy Lgt", "#AFEEEE"),
    ("955", "Aqua Lgt", "#E0FFFF"),
    ("956", "Aqua Vy Lgt", "#F0FFFF"),
    ("957", "Aqua Vy Lgt", "#F5FFFF"),
    ("963", "Dusty Rose Vy Lgt", "#F5E6E8"),
    ("964", "Dusty Rose Lgt", "#E8C8D0"),
    ("965", "Dusty Rose Med", "#D8A0B0"),
    ("966", "Dusty Rose Vy Dk", "#C08090"),
    ("967", "Dusty Rose Dk", "#B06070"),
    ("3685", "Mauve Vy Lgt", "#E8D8E8"),
    ("3686", "Mauve Lgt", "#D8B8D8"),
    ("3687", "Mauve Med", "#C090C0"),
    ("3688", "Mauve Vy Dk", "#A060A0"),
    ("3689", "Mauve Dk", "#805080"),
    ("3690", "Mauve Vy Lgt", "#F0E0F0"),
    ("3691", "Mauve Vy Lgt", "#F8E8F8"),
    ("3692", "Pewter Gray Vy Lgt", "#F0F0F0"),
    ("3693", "Pewter Gray Lgt", "#E0E0E0"),
    ("3694", "Pewter Gray Med", "#C0C0C0"),
    ("3695", "Pewter Gray Vy Dk", "#A0A0A0"),
    ("3696", "Pewter Gray Dk", "#808080"),
    ("3697", "Pewter Gray Vy Dk", "#606060"),
    ("3698", "Pewter Gray Vy Dk", "#404040"),
    ("3790", "Beige Gray Vy Lgt", "#F5F0E8"),
    ("3791", "Beige Gray Lgt", "#E8E0D0"),
    ("3792", "Beige Gray Med", "#D0C8B0"),
    ("3793", "Beige Gray Vy Dk", "#B8A888"),
    ("3794", "Beige Gray Dk", "#A09070"),
    ("3795", "Beige Gray Vy Dk", "#887858"),
    ("3796", "Beige Gray Vy Dk", "#706048"),
    ("3801", "Cyclamen Red Vy Lgt", "#F8C8D8"),
    ("3802", "Cyclamen Red Lgt", "#F0A0B8"),
    ("3803", "Cyclamen Red Med", "#E07090"),
    ("3804", "Cyclamen Red Vy Dk", "#C04070"),
    ("3805", "Cyclamen Red Dk", "#A02050"),
    ("3806", "Cyclamen Red Vy Lgt", "#F8D0E0"),
    ("3807", "Cyclamen Red Vy Lgt", "#FAE0E8"),
    ("3852", "Straw Vy Lgt", "#F5E6C8"),
    ("3853", "Straw Lgt", "#E8D5A0"),
    ("3854", "Straw Med", "#D4C070"),
    ("3855", "Straw Vy Dk", "#C0A848"),
    ("3856", "Straw Dk", "#AC9430"),
    ("3857", "Straw Vy Lgt", "#E8DCC0"),
    ("3858", "Straw Vy Lgt", "#F0E8D8"),
    ("3862", "Mocha Brown Vy Lgt", "#D4C4B0"),
    ("3863", "Mocha Brown Lgt", "#C4B098"),
    ("3864", "Mocha Brown Med", "#B09878"),
    ("3865", "Mocha Brown Vy Dk", "#987850"),
    ("3866", "Mocha Brown Dk", "#806038"),
    ("3867", "Mocha Brown Vy Lgt", "#D8CCA8"),
    ("3868", "Mocha Brown Vy Lgt", "#E0D4B8"),
    ("3869", "Mocha Brown Vy Lgt", "#E8DCC8"),
    ("3870", "Mocha Brown Vy Lgt", "#F0E4D8"),
    ("3871", "Mocha Brown Vy Lgt", "#F8EEE0"),
]


def resolve(color: str) -> str:
    """Return "#rrggbb" for a color spec."""
    if not color:
        return "#000000"
    if color.startswith("#"):
        return color.lower()
    if color.startswith("dmc:"):
        code = color[4:]
        for c, _n, h in DMC_COLORS:
            if c == code:
                return h
        return "#000000"
    return color.lower()


def dmc_name(color: str) -> str | None:
    if not color.startswith("dmc:"):
        return None
    code = color[4:]
    for c, n, _h in DMC_COLORS:
        if c == code:
            return n.strip()
    return None


def nearest_dmc(hex_color: str) -> str:
    """Return 'dmc:NNN' spec nearest to a hex color (RGB distance)."""
    h = resolve(hex_color).lstrip("#")
    if len(h) != 6:
        return "#000000"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    best, bestd = None, 1 << 30
    for code, _n, dh in DMC_COLORS:
        hh = dh.lstrip("#")
        dr, dg, db = int(hh[0:2], 16) - r, int(hh[2:4], 16) - g, int(hh[4:6], 16) - b
        d = dr * dr + dg * dg + db * db
        if d < bestd:
            bestd, best = d, code
    return f"dmc:{best}" if best else "#000000"


def all_colors() -> list[tuple[str, str, str]]:
    """(spec, label, hex) for every palette entry."""
    return [(f"dmc:{c}", f"{c} {n}".strip(), h) for c, n, h in DMC_COLORS]
