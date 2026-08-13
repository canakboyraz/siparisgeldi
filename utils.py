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
    "UnDelivered": "Teslim edilemedi",
    "UnSupplied": "Tedarik edilemedi",
    "AtCollectionPoint": "Teslimat noktasında",
    "UnPacked": "Paket bölündü",
    "Awaiting": "Ödeme bekliyor",
    "Verified": "Doğrulandı",
    "RECEIVED": "Yeni",
    "READY_FOR_PICKUP": "Teslim almaya hazır",
    "DISPATCHED": "Sevk edildi",
    "CANCELED": "İptal",
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
    "UnDelivered": "red",
    "UnSupplied": "red",
    "AtCollectionPoint": "violet",
    "UnPacked": "amber",
    "Awaiting": "gray",
    "Verified": "blue",
    "RECEIVED": "blue",
    "READY_FOR_PICKUP": "amber",
    "DISPATCHED": "violet",
    "CANCELED": "red",
}

_PLATFORM_LABELS = {
    "trendyolgo": "Trendyol Go",
    "trendyolgo_market": "Trendyol Go Market",
    "migros":     "Migros Yemek",
    "trendyol_marketplace": "Trendyol Pazaryeri",
}

_STATUS_LABELS.update({
    "Scheduled": "İleri tarihli",
    "ScheduledApproved": "İleri tarihli onaylandı",
    "AdminCancelled": "Admin iptal",
    "AutoCancelled": "Otomatik iptal",
})

_STATUS_COLORS.update({
    "Scheduled": "blue",
    "ScheduledApproved": "amber",
    "AdminCancelled": "red",
    "AutoCancelled": "red",
})

_PLATFORM_LABELS["getir"] = "Getir Yemek"
_PLATFORM_LABELS["hepsiburada"] = "Hepsiburada"
_PLATFORM_LABELS["yemeksepeti"] = "Yemeksepeti"

_STATUS_LABELS.update({
    "Open": "Yeni",
    "Undelivered": "Teslim edilemedi",
    "Unpacked": "Paket bozuldu",
    "DELIVERED": "Teslim edildi",
})

_STATUS_COLORS.update({
    "Open": "blue",
    "Undelivered": "red",
    "Unpacked": "amber",
    "DELIVERED": "green",
})


def status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status or "-")


def status_color(status: str) -> str:
    return _STATUS_COLORS.get(status, "gray")


def platform_label(platform: str) -> str:
    return _PLATFORM_LABELS.get(platform, platform or "-")
