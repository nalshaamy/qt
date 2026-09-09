# FlexSys POS Device Access — Odoo 19

## هدف الموديول

توفير رابط آمن ثابت لكل جهاز كاشير يربطه مباشرة بنقطة بيع محددة، ويتجاوز صفحات Odoo الإدارية واختيار نقطة البيع، **مع الإبقاء الإلزامي على شاشة إلغاء قفل الكاشير وPIN الموظف**.

المبدأ المعتمد:

- **Secure Token = التحقق من الجهاز**
- **Employee PIN = التحقق من الموظف**

المسار النهائي:

`Secure Device URL -> FlexSys token validation -> Odoo user session -> /pos/ui/<config_id>/login -> Cashier PIN -> POS selling screen`

## ما يتم تجاوزه

- تسجيل دخول Odoo اليدوي
- الصفحة الرئيسية
- اختيار تطبيق نقطة البيع
- اختيار QT001 / QT002 / غيرها

## ما يبقى

- شاشة Odoo الأصلية لإلغاء قفل الكاشير
- PIN الموظف
- تسجيل هوية الكاشير داخل POS قبل البيع

## التصميم الأمني

1. الـToken عشوائي بطول 256-bit تقريبًا باستخدام `secrets.token_urlsafe(32)`.
2. لا يتم تخزين الـToken الخام في سجل الجهاز؛ يتم تخزين SHA-256 فقط.
3. الرابط الخام يظهر مرة واحدة فقط في Wizard عند Generate / Rotate.
4. تدوير Token يلغي الرابط السابق فورًا.
5. يمكن تحديد تاريخ انتهاء صلاحية.
6. يمكن تقييد الجهاز بعنوان IP أو CIDR اختياريًا.
7. يوجد Audit Log لمحاولات النجاح والفشل دون تسجيل الـToken الخام.
8. يوجد Rate Limiting مبدئي على المحاولات الفاشلة حسب IP.
9. يعتمد الموديول على `pos_hr` لضمان وجود Employee Login / PIN في نقطة البيع.
10. يتم إنشاء Odoo session صالحة باستخدام مستخدم تقني محدود الصلاحيات، ثم التحويل إلى مسار POS القياسي.
11. لا يتم تعديل Controller القياسي لنقطة البيع ولا تجاوز PIN الموظف.
12. بعد نجاح PIN فقط، يتم تسجيل اسم الموظف ووقت آخر تحقق على سجل الجهاز، بدون حفظ قيمة PIN نهائيًا.

## الإعداد

بعد تثبيت الموديول:

`Point of Sale -> Configuration -> Device Access -> Devices`

أنشئ Device جديدًا وحدد:

- Device Name
- Company
- Point of Sale
- Technical POS User
- Token expiry (اختياري)
- Allowed IP / CIDR (اختياري)

ثم اضغط **Generate / Rotate Secure Link** وانسخ الرابط إلى اختصار سطح المكتب أو وضع Kiosk للمتصفح على جهاز الكاشير.

## Technical POS User

استخدم مستخدم Odoo داخليًا مخصصًا لهذا الغرض بصلاحيات Point of Sale الضرورية فقط. لا تستخدم Administrator أو Settings user. هذا المستخدم يمثل **الجهاز/الجلسة التقنية** وليس الكاشير الفعلي؛ الكاشير الفعلي يتم تحديده بواسطة PIN داخل POS.

## Config Parameters

يمكن ضبط القيم التالية من `ir.config_parameter` عند الحاجة:

- `flexsys_pos_device_access.rate_limit_max_failed` — الافتراضي `10`
- `flexsys_pos_device_access.rate_limit_window_seconds` — الافتراضي `60`
- `flexsys_pos_device_access.log_retention_days` — الافتراضي `90`

## ملاحظة مهمة عن IP

في Odoo.sh / Cloudflare يجب اختبار القيمة الفعلية التي تصل إلى `remote_addr` قبل تفعيل Allowed IP في الإنتاج. اترك الحقل فارغًا أثناء الاختبار الأول.

## Acceptance Criteria

- فتح Secure URL صالح ينتقل إلى `/pos/ui/<config_id>/login`.
- لا تظهر الصفحة الرئيسية أو شاشة اختيار نقاط البيع.
- شاشة PIN تبقى كما هي.
- PIN الصحيح يدخل إلى نقطة البيع.
- Token ملغى/منتهي/خاطئ لا يعمل.
- الـToken الخام لا يُكتب في **Audit Logs الخاصة بالموديول**؛ يتم حفظ بصمة SHA-256 مختصرة فقط. ملاحظة: رابط V1 نفسه قد يظهر في Browser/HTTP access history حسب البنية التحتية، لذلك يجب استخدام HTTPS وعدم مشاركة الرابط.
- Service User لا يمكن أن يكون System Administrator.
- نقطة البيع يجب أن يكون فيها Employee Login (`module_pos_hr`) مفعّلًا.
- نجاح PIN يسجل اسم الموظف/الوقت فقط ولا يسجل PIN نفسه.
- محاولة الوصول تسجل في Access Logs.

## Deployment Status

هذه النسخة اجتازت فحوصات static للبنية وPython/XML، لكنها يجب أن تُثبت أولًا على **Odoo.sh Staging** وتُختبر end-to-end قبل Production، خصوصًا إنشاء الـsession، تحميل POS assets، وقراءة IP خلف Odoo.sh/Cloudflare.
