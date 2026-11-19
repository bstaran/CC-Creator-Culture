package com.sub9.productservice.architecture;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;
import com.tngtech.archunit.library.freeze.FreezingArchRule;
import org.junit.jupiter.api.DisplayName;

/**
 * 계층 규칙(루트 CLAUDE.md "코드 구조 규칙") 검사.
 *
 * <p>기존 위반은 src/test/resources/archunit_store 에 동결되어 있어 통과한다. 새 위반이 생기면 실패한다.
 * 기존 위반을 고치면 저장소에서 자동으로 빠진다. 규칙 이름(as)을 바꾸면 동결 기록과 연결이 끊기므로 바꾸지 않는다.
 */
@DisplayName("계층 아키텍처 규칙")
@AnalyzeClasses(packages = "com.sub9.productservice", importOptions = ImportOption.DoNotIncludeTests.class)
class LayerArchitectureTest {

    private static final ArchRule DOMAIN_RULE = FreezingArchRule.freeze(
            noClasses().that().resideInAPackage("..domain..")
                    .should().dependOnClassesThat().resideInAnyPackage(
                            "..application..", "..infrastructure..", "..presentation..")
                    .as("domain does not depend on application, infrastructure, presentation"));

    private static final ArchRule APPLICATION_RULE = FreezingArchRule.freeze(
            noClasses().that().resideInAPackage("..application..")
                    .should().dependOnClassesThat().resideInAnyPackage(
                            "..infrastructure..", "..presentation..")
                    .as("application does not depend on infrastructure, presentation"));

    @ArchTest
    @DisplayName("domain 계층은 application, infrastructure, presentation 계층에 의존하지 않는다")
    void domainDoesNotDependOnOuterLayers(JavaClasses classes) {
        DOMAIN_RULE.check(classes);
    }

    @ArchTest
    @DisplayName("application 계층은 infrastructure, presentation 계층에 의존하지 않는다")
    void applicationDoesNotDependOnInfrastructureOrPresentation(JavaClasses classes) {
        APPLICATION_RULE.check(classes);
    }
}
