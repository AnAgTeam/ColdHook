import XCTest

final class TestSwiftAppUITests: XCTestCase {
    @MainActor
    func testSharedHooksAreVisible() throws {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.staticTexts["Framework value: 777"].waitForExistence(timeout: 5))
        app.buttons["Trigger url(for:)"] .tap()
        let patched = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH[c] %@", "patched by simulator ho")).firstMatch
        XCTAssertTrue(patched.waitForExistence(timeout: 10))
    }
}
