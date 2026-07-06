// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// A small, dependency-free HTML-to-text converter for card fields. Anki note
// fields carry light HTML (bold, italics, line breaks, entities) plus the odd
// image tag. Rendering the raw markup would show tag soup, so this strips the
// tags, turns block/break boundaries into newlines, and decodes the common HTML
// entities. It is deliberately lightweight: MathJax (\( .. \) / $ .. $) is left
// as authored (a full math renderer is out of scope for the companion), and no
// remote resources are fetched. NSAttributedString's HTML importer is avoided on
// purpose (it is main-thread-only, slow, and network-capable).

import Foundation

enum HTMLText {
    /// Convert an HTML field into readable plain text: block-level and <br> tags
    /// become newlines, all other tags are dropped, entities are decoded, and
    /// runs of blank lines/space are collapsed. Returns a trimmed string.
    static func plain(from html: String) -> String {
        guard !html.isEmpty else { return "" }
        var text = html

        // Normalize line-break-producing tags to newlines before stripping.
        for pattern in ["<br\\s*/?>", "</p>", "</div>", "</li>", "</h[1-6]>", "</tr>"] {
            text = replaceRegex(pattern, in: text, with: "\n")
        }
        // A list item opens with a bullet; a horizontal rule is a divider line.
        text = replaceRegex("<li[^>]*>", in: text, with: "\u{2022} ")
        text = replaceRegex("<hr\\s*/?>", in: text, with: "\n")

        // Drop every remaining tag.
        text = replaceRegex("<[^>]+>", in: text, with: "")

        text = decodeEntities(text)

        // Collapse runs of spaces/tabs, then trim excess blank lines.
        text = replaceRegex("[ \\t]+", in: text, with: " ")
        text = replaceRegex("\\n{3,}", in: text, with: "\n\n")
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // MARK: - Helpers

    private static func replaceRegex(_ pattern: String, in text: String, with template: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return text
        }
        let range = NSRange(text.startIndex..., in: text)
        return regex.stringByReplacingMatches(in: text, options: [], range: range, withTemplate: template)
    }

    /// The named entities Anki fields realistically use, plus numeric (&#123;
    /// and &#x1F;) forms. Anything unrecognized is left untouched.
    private static let namedEntities: [String: String] = [
        "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": "\"",
        "&apos;": "'", "&#39;": "'", "&nbsp;": " ", "&ndash;": "\u{2013}",
        "&mdash;": "\u{2014}", "&hellip;": "\u{2026}", "&times;": "\u{00D7}",
        "&divide;": "\u{00F7}", "&deg;": "\u{00B0}", "&plusmn;": "\u{00B1}",
        "&micro;": "\u{00B5}", "&alpha;": "\u{03B1}", "&beta;": "\u{03B2}",
        "&gamma;": "\u{03B3}", "&delta;": "\u{03B4}", "&pi;": "\u{03C0}",
        "&theta;": "\u{03B8}", "&lambda;": "\u{03BB}", "&omega;": "\u{03C9}",
        "&mu;": "\u{03BC}", "&sigma;": "\u{03C3}", "&rarr;": "\u{2192}",
    ]

    private static func decodeEntities(_ text: String) -> String {
        guard text.contains("&") else { return text }
        var result = text
        for (entity, replacement) in namedEntities {
            result = result.replacingOccurrences(of: entity, with: replacement, options: [.caseInsensitive])
        }
        result = decodeNumericEntities(result)
        return result
    }

    /// Decode `&#NN;` (decimal) and `&#xNN;` (hex) numeric character references.
    private static func decodeNumericEntities(_ text: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: "&#(x?)([0-9a-fA-F]+);") else {
            return text
        }
        let nsText = text as NSString
        var result = ""
        var lastEnd = 0
        let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))
        for match in matches {
            result += nsText.substring(with: NSRange(location: lastEnd, length: match.range.location - lastEnd))
            let isHex = nsText.substring(with: match.range(at: 1)) == "x"
            let digits = nsText.substring(with: match.range(at: 2))
            if let code = UInt32(digits, radix: isHex ? 16 : 10), let scalar = Unicode.Scalar(code) {
                result.append(Character(scalar))
            } else {
                result += nsText.substring(with: match.range)
            }
            lastEnd = match.range.location + match.range.length
        }
        result += nsText.substring(from: lastEnd)
        return result
    }
}
