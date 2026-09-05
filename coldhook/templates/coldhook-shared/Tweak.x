#import <Foundation/Foundation.h>

// Shared hook: binary selector is explicit and stored in the hook dylib metadata.
%hookf_shared("MainBinary", const char *, domain_for, int env) {
    return "shared replacement";
}

%ctor {
    NSLog(@"[@@PROJECTNAME@@] shared hook loaded");
}
