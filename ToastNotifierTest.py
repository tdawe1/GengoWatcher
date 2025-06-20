from win10toast import ToastNotifier

notifier = ToastNotifier()
notifier.show_toast("Test Notification", "If you see this, it's working!", duration=5)
