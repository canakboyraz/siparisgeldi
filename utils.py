"""Şablon yardımcıları — durum etiketleri, renkler, platform adları."""

_STATUS_LABELS = {
    "Created":    "Yeni",
    "Picking":    "Kabul edildi",
    "Invoiced":   "Hazırlandı",
    "Shipped":    "Yolda",
    "Delivered":  "Teslim edildi",
    "Cancelled":  "İptal",
    "UnSupplied": "Restoran iptal",
}

_STATUS_COLORS = {
    "Created":    "blue",
    "Picking":    "amber",
    "Invoiced":   "amber",
    "Shipped":    "violet",
    "Delivered":  "green",
    "Cancelled":  "red",
    "UnSupplied": "red",
}

_PLATFORM_LABELS = {
    "trendyolgo": "Trendyol Go",
    "migros":     "Migros Yemek",
}


def status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status or "-")


def status_color(status: str) -> str:
    return _STATUS_COLORS.get(status, "gray")


def platform_label(platform: str) -> str:
    return _PLATFORM_LABELS.get(platform, platform or "-")
