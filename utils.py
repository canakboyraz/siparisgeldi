"""Şablon yardımcıları — durum etiketleri, renkler, platform adları."""

_STATUS_LABELS = {
    "Created":    "Yeni",
    "NEW_PENDING": "Yeni",
    "Pending":    "Bekliyor",
    "New":        "Yeni",
    "Picking":    "Kabul edildi",
    "Invoiced":   "Hazırlandı",
    "Approved":   "Kabul edildi",
    "Prepared":   "Hazırlandı",
    "Shipped":    "Yolda",
    "Delivery":   "Yolda",
    "OnDelivery": "Yolda",
    "On_Delivery": "Yolda",
    "Delivered":  "Teslim edildi",
    "Completed":  "Tamamlandı",
    "Cancelled":  "İptal",
    "UnSupplied": "Restoran iptal",
    "Rejected":   "Reddedildi",
    "Refunded":   "İade",
    "Returned":   "İade",
}

_STATUS_COLORS = {
    "Created":    "blue",
    "NEW_PENDING": "blue",
    "Pending":    "blue",
    "New":        "blue",
    "Picking":    "amber",
    "Invoiced":   "amber",
    "Approved":   "amber",
    "Prepared":   "amber",
    "Shipped":    "violet",
    "Delivery":   "violet",
    "OnDelivery": "violet",
    "On_Delivery": "violet",
    "Delivered":  "green",
    "Completed":  "green",
    "Cancelled":  "red",
    "UnSupplied": "red",
    "Rejected":   "red",
    "Refunded":   "red",
    "Returned":   "red",
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
