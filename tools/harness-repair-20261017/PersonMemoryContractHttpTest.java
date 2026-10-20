package xiaozhi.modules.personmemory;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.http.MediaType;

class PersonMemoryContractHttpTest {
    PersonMemoryService service;
    RecentArchiveService recent;
    MockMvc http;
    static final String ACTOR = "{\"account_id\":99001,\"person_id\":\"usr_test\",\"generation\":0,\"directory_version\":1,\"turn_id\":\"test-turn\",\"device_id\":\"test-device\",\"agent_id\":\"test-agent\",\"status\":\"matched\"}";

    @BeforeEach void setup() {
        service=mock(PersonMemoryService.class);recent=mock(RecentArchiveService.class);
        http=MockMvcBuilders.standaloneSetup(new PersonMemoryController(service,mock(PersonBehaviorService.class),recent)).build();
    }
    @Test void addEndpointAcceptsPythonContractAndReturnsReceipt() throws Exception {
        when(service.add(any(),eq("我最爱喝咖啡"))).thenReturn(Map.of("local_applied",true,"record_id","material:1"));
        http.perform(post("/person-memory/internal/add").contentType(MediaType.APPLICATION_JSON)
            .content("{\"actor\":"+ACTOR+",\"fact\":\"我最爱喝咖啡\"}"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
            .andExpect(jsonPath("$.data.record_id").value("material:1"));
        verify(service).add(any(),eq("我最爱喝咖啡"));
    }
    @Test void invalidAddNeverReachesWriter() throws Exception {
        http.perform(post("/person-memory/internal/add").contentType(MediaType.APPLICATION_JSON)
            .content("{\"actor\":"+ACTOR+",\"fact\":\"\"}"))
            .andExpect(status().isBadRequest());
        verifyNoInteractions(service);
    }
    @Test void readbackPassesExactIdsToScopedService() throws Exception {
        when(recent.search(any(),eq("我最爱喝咖啡"),eq("related"),eq(1),eq(List.of("material:1"))))
            .thenReturn(Map.of("status","ok","items",List.of(Map.of("record_id","material:1","text","我最爱喝咖啡"))));
        http.perform(post("/person-memory/internal/recent").contentType(MediaType.APPLICATION_JSON)
            .content("{\"actor\":"+ACTOR+",\"query\":\"我最爱喝咖啡\",\"recordIds\":[\"material:1\"]}"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.data.items[0].record_id").value("material:1"));
        verify(recent).search(any(),eq("我最爱喝咖啡"),eq("related"),eq(1),eq(List.of("material:1")));
    }
}
