import XCTest

final class TestSwiftAppUITests: XCTestCase {
    @MainActor
    func testSharedHooksAreVisible() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-label", "Fail text"]
        app.launch()
        defer { app.terminate() }
        XCTAssertTrue(app.staticTexts["True text (instead of Fail text)"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Framework value: 777"].waitForExistence(timeout: 5))
        app.buttons["Trigger url(for:)"] .tap()
        let patched = app.staticTexts["patched by simulator hook"]
        XCTAssertTrue(patched.waitForExistence(timeout: 10))
    }
}
