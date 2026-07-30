package example;

import static io.gatling.javaapi.core.CoreDsl.*;
import static io.gatling.javaapi.http.HttpDsl.*;

import io.gatling.javaapi.core.*;
import io.gatling.javaapi.http.*;

import java.time.Duration;

public class BasicSimulation extends Simulation {

  // Define HTTP configuration with connection management
  // Reference: https://docs.gatling.io/reference/script/protocols/http/protocol/
  private static final HttpProtocolBuilder httpProtocol = http
      .baseUrl("https://api-ecomm.gatling.io")
      .acceptHeader("application/json")
      .userAgentHeader("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")
      // Connection management settings to prevent resource accumulation
      .connectionHeader("keep-alive")
      .maxConnectionsPerHost(10)  // Limit connections per host
      .shareConnections();         // Reuse connections across virtual users

  // Define scenario with proper session management
  // Reference: https://docs.gatling.io/reference/script/core/scenario/
  private static final ScenarioBuilder scenario = scenario("API Load Test")
      .exec(http("Get Session")
          .get("/session")
          .check(status().is(200))  // Validate response status
          .check(responseTimeInMillis().lte(5000))) // Response time validation
      .pause(Duration.ofMillis(500), Duration.ofSeconds(2)); // Realistic think time

  // Define comprehensive assertions
  // Reference: https://docs.gatling.io/reference/script/core/assertions/
  private static final Assertion[] assertions = {
      global().failedRequests().count().lt(1L),
      global().responseTime().max().lt(10000),
      global().responseTime().percentile3().lt(2000),
      global().successfulRequests().percent().gt(99.0)
  };

  /**
   * Load profile configuration supporting various test types
   * @return OpenInjectionStep for open workload model
   */
  public static OpenInjectionStep openLoadProfile() {
    String injectType = System.getProperty("injectType", "constantUsersPerSec");
    int users = Integer.getInteger("users", 10);
    int duration = Integer.getInteger("duration", 30);
    int rampDuration = Integer.getInteger("rampDuration", 60);
    int usersStart = Integer.getInteger("usersStart", users / 2);
    int usersEnd = Integer.getInteger("usersEnd", users);
    System.out.println("Inject Type: " + injectType);
    System.out.println("Users: " + users);
    System.out.println("Duration: " + duration);
    System.out.println("Ramp Duration: " + rampDuration);
    System.out.println("Users Start: " + usersStart);
    System.out.println("Users End: " + usersEnd);

    switch (injectType.toLowerCase()) {
      case "soaktest":
        // Gradual ramp up followed by sustained load - ideal for soak tests
        return rampUsers(users).during(Duration.ofSeconds(rampDuration));
        
      case "capacitytest":
        // Gradual increase to find capacity limits
        return rampUsersPerSec(1).to(users).during(Duration.ofSeconds(duration));
        
      case "stresspeakusers":
        return stressPeakUsers(users).during(Duration.ofSeconds(duration));
        
      case "rampuserspersec":
        return rampUsersPerSec(usersStart).to(usersEnd).during(Duration.ofSeconds(duration));
        
      case "constantusers":
        // Constant number of users (not rate)
        return rampUsers(users).during(Duration.ofSeconds(rampDuration));
        
      default:
        return constantUsersPerSec(users).during(Duration.ofSeconds(duration));
    }
  }

  /**
   * Closed workload model - better for soak tests as it maintains constant concurrent users
   * @return ClosedInjectionStep for closed workload model
   */
  public static ClosedInjectionStep closedLoadProfile() {
    int users = Integer.getInteger("users", 10);
    int duration = Integer.getInteger("duration", 30);
    int rampDuration = Integer.getInteger("rampDuration", 60);

    String injectType = System.getProperty("injectType", "constantUsersPerSec");
    
    switch (injectType.toLowerCase()) {
      case "soaktest":
      case "capacitytest":
        // For soak/capacity tests, ramp up to target concurrent users then maintain
        return rampConcurrentUsers(1).to(users).during(Duration.ofSeconds(duration));
      default:
        return constantConcurrentUsers(users).during(Duration.ofSeconds(duration));
    }
  }

  /**
   * Determine which workload model to use based on test type
   */
  private PopulationBuilder getPopulationBuilder() {
    String workloadModel = System.getProperty("workloadModel", "open");
    String injectType = System.getProperty("injectType", "constantUsersPerSec");
    
    // Use closed model for soak and capacity tests by default, or when explicitly specified
    if ("closed".equalsIgnoreCase(workloadModel) || 
        "soaktest".equalsIgnoreCase(injectType) || 
        "capacitytest".equalsIgnoreCase(injectType)) {
      return scenario.injectClosed(closedLoadProfile());
    } else {
      return scenario.injectOpen(openLoadProfile());
    }
  }

  // Setup and execute the test
  {
    setUp(getPopulationBuilder())
        .protocols(httpProtocol)
        .assertions(assertions);
  }
}