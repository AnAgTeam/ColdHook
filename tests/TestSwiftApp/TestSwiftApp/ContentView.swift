//
//  ContentView.swift
//  TestSwiftApp
//
//  Created by toilett on 02.06.2026.
//

import SwiftUI
import TestFramework

private func frameworkLabel() -> String { "Framework value: \(frameworkProbe())" }

// Мишень №1: подмена возвращаемой строки.
// @inline(never) — чтобы функция осталась отдельной с символом, а не заинлайнилась в body.
@inline(never)
func get_label_content() -> String {
    // Берём из рантайм-конфига → не сворачивается в константу, выживает как символ.
    // По умолчанию "Fail text"; хук может подменить возврат и сменить лейбл.
    return UserDefaults.standard.string(forKey: "label") ?? "Fail text"
}

// Мишень №2: типовой краш реального приложения —
// switch по домену, в default безусловный assertionFailure.
// ColdHook должен либо убрать assert, либо подменить возврат на валидный домен.
@inline(never)
func url(for domain: String) -> String {
    switch domain {
    case "application":
        return "https://real.domain/app"
    default:
        // preconditionFailure переживает -O (Release), в отличие от assertionFailure.
        // Даёт brk-в-конце функции — мишень для патча.
        preconditionFailure("Fatal error")
    }
}

struct ContentView: View {
    @State private var result = ""

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "globe")
                .imageScale(.large)
                .foregroundStyle(.tint)
            Text(get_label_content())
            Text(frameworkLabel())

            // Тап вызывает url(for:) с неизвестным доменом → assertionFailure.
            // После патча ColdHook здесь должна вернуться строка вместо краша.
            Button("Trigger url(for:)") {
                result = url(for: "unknown")
            }
            Text(result)
        }
        .padding()
    }
}
