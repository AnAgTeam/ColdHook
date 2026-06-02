//
//  ViewController.m
//  TestApp
//
//  Created by toilett on 02.06.2026.
//

#import "ViewController.h"

NSString* get_label_text(void) {
    return @"Fail text";
}

@interface ViewController ()

@end

@implementation ViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    
    UILabel* label = [UILabel new];
    label.text = get_label_text();
    
    label.translatesAutoresizingMaskIntoConstraints = NO;
    [label.centerYAnchor constraintEqualToAnchor:self.view.layoutMarginsGuide.centerYAnchor].active = YES;
    [label.centerXAnchor constraintEqualToAnchor:self.view.layoutMarginsGuide.centerXAnchor].active = YES;
}


@end
