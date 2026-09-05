# The decision engine is pure Kotlin with no reflection; nothing extra is required.
# Keep the listener service entry point, which the system binds by name.
-keep class com.attentionai.service.AttentionListenerService { *; }
-keep class com.attentionai.service.FeedbackReceiver { *; }
