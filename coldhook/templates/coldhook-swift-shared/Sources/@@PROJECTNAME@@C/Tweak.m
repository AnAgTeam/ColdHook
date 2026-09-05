#include <coldhook.h>

extern void ch_hook(void);

// Replace the binary selector and mangled Swift symbol (without leading '_').
CH_DYN_SYM("MainBinary", "$s12YourModule6target3argS2S_tF", ch_hook);
// Address alternative:
// CH_DYN_ADDR("MainBinary", 0x100004298, ch_hook);
