import XCTest

// DGX-782 H2-b1: falla a propósito para ver el run rojo de app-pruebas.yml. Se quita en el commit siguiente.
final class CiPruebaTests: XCTestCase {
    func testFallaAProposito() { XCTFail("el job de pruebas ejecuta swift test de verdad") }
}
