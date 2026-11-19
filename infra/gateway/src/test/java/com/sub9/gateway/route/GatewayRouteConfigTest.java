package com.sub9.gateway.route;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.http.server.PathContainer;
import org.springframework.web.util.pattern.PathPattern;
import org.springframework.web.util.pattern.PathPatternParser;
import org.yaml.snakeyaml.Yaml;

@DisplayName("게이트웨이 라우트 설정")
class GatewayRouteConfigTest {

    private static final List<String> ENVS = List.of("local", "dev", "prod");
    private static final PathPatternParser PARSER = new PathPatternParser();

    record Route(String id, String uri, List<PathPattern> patterns) {}

    static Stream<Arguments> cases() {
        List<Arguments> list = new ArrayList<>();
        for (String env : ENVS) {
            list.add(Arguments.of(env, "PATCH", "/api/v1/admin/products/1/status", "product-service"));
            list.add(Arguments.of(env, "POST", "/api/v1/images/presigned-url", "product-service"));
            list.add(Arguments.of(env, "GET", "/api/v1/products/1", "product-service"));
            list.add(Arguments.of(env, "POST", "/api/v1/orders", "order-service"));
            list.add(Arguments.of(env, "POST", "/api/v1/auth/login", "user-service"));
        }
        return list.stream();
    }

    @ParameterizedTest(name = "[{0}] {1} {2} -> {3}")
    @MethodSource("cases")
    @DisplayName("요청 경로는 기대한 서비스 라우트로 매칭된다")
    void routesRequestToExpectedService(
            String env, String method, String path, String expectedService) {
        List<Route> routes = loadRoutes(env);

        String actual =
                routes.stream()
                        .filter(r -> r.patterns().stream().anyMatch(p -> p.matches(PathContainer.parsePath(path))))
                        .map(r -> r.id() + " (" + r.uri() + ")")
                        .findFirst()
                        .orElse("없음");

        assertThat(actual)
                .withFailMessage(
                        "환경=%s, 요청=%s %s, 기대 서비스=%s, 실제 매칭 라우트=%s",
                        env, method, path, expectedService, actual)
                .startsWith(expectedService + " ");
    }

    @SuppressWarnings("unchecked")
    private static List<Route> loadRoutes(String env) {
        Path file = Path.of("../../config-repo/gateway-" + env + ".yaml").toAbsolutePath().normalize();
        assertThat(file)
                .withFailMessage("게이트웨이 설정 파일을 찾을 수 없습니다: %s", file)
                .exists();
        try (InputStream in = Files.newInputStream(file)) {
            Map<String, Object> root = new Yaml().load(in);
            Map<String, Object> spring = (Map<String, Object>) root.get("spring");
            Map<String, Object> cloud = (Map<String, Object>) spring.get("cloud");
            Map<String, Object> gateway = (Map<String, Object>) cloud.get("gateway");
            Map<String, Object> server = (Map<String, Object>) gateway.get("server");
            Map<String, Object> webflux = (Map<String, Object>) server.get("webflux");
            List<Map<String, Object>> rawRoutes = (List<Map<String, Object>>) webflux.get("routes");
            List<Route> routes = new ArrayList<>();
            for (Map<String, Object> raw : rawRoutes) {
                List<PathPattern> patterns = new ArrayList<>();
                for (String predicate : (List<String>) raw.get("predicates")) {
                    if (predicate.startsWith("Path=")) {
                        for (String p : predicate.substring("Path=".length()).split(",")) {
                            patterns.add(PARSER.parse(p.trim()));
                        }
                    }
                }
                routes.add(new Route((String) raw.get("id"), (String) raw.get("uri"), patterns));
            }
            return routes;
        } catch (IOException e) {
            throw new IllegalStateException("게이트웨이 설정 파일을 읽을 수 없습니다: " + file, e);
        }
    }
}
