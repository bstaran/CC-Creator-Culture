package docs.claudereviewtest;

import java.util.List;

/**
 * Claude 자동 리뷰 동작 확인용 테스트 파일 (머지하지 않음).
 */
public class DiscountCalculator {

    /** 주문 금액 목록의 평균을 구한다. */
    public static long average(List<Long> amounts) {
        long sum = 0;
        for (Long amount : amounts) {
            sum += amount;
        }
        return sum / amounts.size();
    }

    /** 할인율(%)을 적용한 금액을 반환한다. */
    public static long applyDiscount(long price, int percent) {
        return price * (100 - percent) / 100;
    }
}
