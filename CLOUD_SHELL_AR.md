# النقل السحابي من Google Drive

هذه الطريقة تشغّل أداة بناء حزمة البيانات في Google Cloud Shell بدل GitHub Actions.
لا تنشئ خادم Compute Engine أو حاوية تخزين مدفوعة. تبقى ملفات البيانات في GitHub Releases.

1. افتح https://shell.cloud.google.com وسجّل الدخول بحساب Google.
2. بعد ظهور الطرفية، نفّذ الأمرين التاليين:

```bash
curl --fail --location https://raw.githubusercontent.com/Moatezsager/pes26ar-updates/main/scripts/cloud-shell.sh -o /tmp/pes26ar-cloud-shell.sh
bash /tmp/pes26ar-cloud-shell.sh
```

ستُفحص المساحة المؤقتة قبل تنزيل الحزمة، والمطلوب 11 GiB متاحة على الأقل.
مساحة HOME الدائمة، المحدودة بـ5 GB، لا تُستخدم لتخزين الأرشيف.
إن لم تتوفر المساحة فسيتوقف السكربت دون إنشاء مورد مدفوع.

عند ظهور رمز تسجيل GitHub افتح الرابط الذي تعرضه الأداة، وأدخل الرمز بحساب Moatezsager.
لا ترسل رمز الوصول أو كلمة المرور لأي شخص. تُحفظ بيانات دخول الأداة في إعداد مؤقت خاص بهذه المهمة.
بعد نجاح المهمة تسجّل الأداة خروج GitHub تلقائيًا. إن أوقفت المهمة مبكرًا وأردت إبطال جلسة الأداة، نفّذ:

```bash
GH_CONFIG_DIR=/tmp/pes26ar-cloud-import/github-config gh auth logout --hostname github.com --user Moatezsager
```

تحتاج Cloud Shell إلى جلسة تفاعلية؛ الجلسات غير التفاعلية تتوقف بعد 40 دقيقة، والحد الأقصى للجلسة 12 ساعة.
لا يتضمن السكربت حيلًا لتجاوز مهلة الخمول. إذا توقفت الجلسة يمكن تشغيله مرة أخرى؛ يتجاوز أجزاء GitHub التي تطابق البصمة والحجم.
قد تضيع ملفات /tmp عندما تنتهي الآلة، مما يستدعي إعادة تنزيل المصدر سحابيًا. الأجزاء المكتملة في GitHub تبقى موجودة.

ترفع الأداة ملفات اللعبة والباتش المعتمدة فقط، وتتحقق من SHA-256، وتدمج تحديث الصور الذي جرى فحصه.
تُنشئ إصدارًا مسودة يحتوي أجزاء 16 MiB وmanifest.json. لا تنشره ولا تفعّل تنزيل التطبيق تلقائيًا قبل المراجعة.

مراجع:
- https://cloud.google.com/shell/pricing
- https://docs.cloud.google.com/shell/docs/quotas-limits

لم يُختبر النقل الكامل في Cloud Shell بعد؛ نجاحه يعتمد أيضًا على توفر الخدمة، المساحة، وصول Google Drive وصلاحيات GitHub.
