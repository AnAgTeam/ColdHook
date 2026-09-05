import Foundation
@_silgen_name("orig_url") private func orig_url(for domain: String) -> String
@_silgen_name("url") public func url(for domain: String) -> String { domain == "unknown" ? "patched by simulator hook" : orig_url(for: domain) }
@_silgen_name("orig_getLabelContent") private func orig_getLabelContent() -> String
@_silgen_name("getLabelContent") public func getLabelContent() -> String { "True text (instead of \(orig_getLabelContent()))" }
@_silgen_name("orig_frameworkProbe") private func orig_frameworkProbe() -> Int32
@_silgen_name("frameworkProbe") public func frameworkProbe() -> Int32 { 777 }
