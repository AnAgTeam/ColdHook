#include "coldhook.h"
extern void url(void); __attribute__((used)) static void *keep_url = (void *)&url;
CH_DYN_SYM("TestSwiftApp", "$s12TestSwiftApp3url3forS2S_tF", url);
extern void getLabelContent(void); __attribute__((used)) static void *keep_label = (void *)&getLabelContent;
CH_DYN_SYM("TestSwiftApp", "$s12TestSwiftApp17get_label_contentSSyF", getLabelContent);
extern void frameworkProbe(void); __attribute__((used)) static void *keep_framework = (void *)&frameworkProbe;
CH_DYN_SYM("TestFramework", "$s13TestFramework14frameworkProbes5Int32VyF", frameworkProbe);
