// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pins the reliability diagram's pure logic: the px()/py() coordinate transform
// ported from ReliabilityDiagram.svelte, and the Brier formatting (round to three
// decimals, trailing zeros trimmed). The Canvas drawing itself is not unit-tested.

import XCTest

final class ReliabilityDiagramTests: XCTestCase {
    // MARK: Coordinate transform

    func testGeometryMapsUnitSquareToTheAxes() {
        // Default size 220, pad 28, tail 10 -> span 182, matching the Svelte.
        let geo = ReliabilityGeometry(size: 220)
        XCTAssertEqual(geo.span, 182, accuracy: 1e-9)

        // x grows left to right from the left axis.
        XCTAssertEqual(geo.x(0), 28, accuracy: 1e-9)
        XCTAssertEqual(geo.x(1), 210, accuracy: 1e-9)
        XCTAssertEqual(geo.x(0.5), 119, accuracy: 1e-9)

        // y is flipped: observed 0 sits on the bottom axis, observed 1 near the top.
        XCTAssertEqual(geo.y(0), 192, accuracy: 1e-9)
        XCTAssertEqual(geo.y(1), 10, accuracy: 1e-9)
        XCTAssertEqual(geo.y(0.5), 101, accuracy: 1e-9)
    }

    func testGeometryScalesWithSize() {
        let geo = ReliabilityGeometry(size: 200)
        XCTAssertEqual(geo.span, 162, accuracy: 1e-9)
        XCTAssertEqual(geo.x(0), 28, accuracy: 1e-9)
        XCTAssertEqual(geo.y(0), 172, accuracy: 1e-9)
        XCTAssertEqual(geo.x(1), 190, accuracy: 1e-9)
    }

    // MARK: Brier formatting

    func testFormatBrierRoundsToThreeDecimals() {
        // The embedded Memory/Performance Brier scores from calibration_evidence.
        XCTAssertEqual(ReliabilityDiagram.formatBrier(0.23376769284759738), "0.234")
        XCTAssertEqual(ReliabilityDiagram.formatBrier(0.17523368467276343), "0.175")
    }

    func testFormatBrierTrimsTrailingZeros() {
        XCTAssertEqual(ReliabilityDiagram.formatBrier(0.17), "0.17")
        XCTAssertEqual(ReliabilityDiagram.formatBrier(0.2), "0.2")
        XCTAssertEqual(ReliabilityDiagram.formatBrier(0.0), "0")
    }

    func testFormatBrierNilIsNil() {
        XCTAssertNil(ReliabilityDiagram.formatBrier(nil))
    }
}
